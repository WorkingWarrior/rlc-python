"""RealLive LZ77 compression and XOR masking from ``lzcomp.h``/``lz_comp_rl.cpp``."""

import struct

XOR_MASK = bytes.fromhex(
    "8be55dc3a1e030440085c074095f5e33c05b8be55dc38b450c85c075148b55ec"
    "83c220526a00e8f528010083c40889450c8b45e46a006a005053ff1534b14300"
    "8b451085c074058b4dec89088a45f084c07578a1e03044008b7de88b750c85c0"
    "75448b1dd0b0430085ff763781ff000004006a0076438b45f88d55fc52680000"
    "04005650ff152cb143006a05ffd3a1e030440081ef0000040081c60000040085c0"
    "74c58b5df853e8f4fbffff8b450c83c4045f5e5b8be55dc38b55f88d4dfc51"
    "575652ff152cb14300ebd88b45e883c020506a00e8472801008b7de88945f48b"
    "f0a1e030440083c40885c075568b1dd0b0430085ff764981ff000004006a0076"
)


def apply_mask(data: bytes) -> bytes:
    return bytes(value ^ XOR_MASK[index & 255] for index, value in enumerate(data))


def lz77_compress(source: bytes) -> bytes:
    """Transcription of ``LZComp<CInfoRealLive>`` including lazy matching."""
    length = len(source)
    if length <= 3:
        return _pack([("raw", bytes((value,))) for value in source])
    heads = [-1] * 32768
    previous = [-1] * (length + 256)
    hash_value = 0

    def update(index):
        nonlocal hash_value
        # The C implementation keeps a 256-byte guard area after the active
        # window.  Its contents cannot affect a valid match, but are read while
        # priming hashes for the final two positions.
        value = source[index] if index < length else 0
        hash_value = (((hash_value << 5) & 0xFFE0) | (value & 0x1F)) & 0x7FFF

    update(0)
    update(1)

    def insert(pos):
        update(pos + 2)
        prior = heads[hash_value]
        previous[pos] = prior
        heads[hash_value] = pos
        return prior

    def longest(pos, chain, old_length):
        best_length = 0
        best_pos = -1
        searches = 4 if old_length >= 4 else 16
        first = max(0, pos - 4095)
        # This deliberately looks surprising.  CInfoRealLive overrides
        # MaxMatch() with 17, but inherits the *static* CInfo::MinLookahead()
        # body.  C++ binds the MaxMatch() call inside that body to
        # CInfo::MaxMatch() (258), so the historical compressor compares up
        # to 258 + MinMatch(3) + 1 = 262 bytes while choosing a candidate,
        # and only afterwards clamps the selected match to 17 bytes.  The
        # extra comparison changes tie-breaking between equal 17-byte tokens.
        limit = min(262, length - pos)
        for _ in range(searches):
            if chain < first or chain >= pos:
                break
            matched = 0
            while matched < limit and source[pos + matched] == source[chain + matched]:
                matched += 1
            if matched > best_length:
                best_length = matched
                best_pos = chain
                # LongestMatch compares eight bytes per loop and checks
                # ``d >= d_end`` after selecting a new best match.  A
                # mismatch on the last available byte has already advanced
                # d to d_end, so the C++ chain traversal stops even though
                # that byte itself did not match.  This is observable in the
                # last few bytes of real scenarios.
                if matched >= limit - 1:
                    break
            chain = previous[chain]
        return min(best_length, 17), best_pos

    tokens = []
    pos = 0
    chain = insert(0)
    match_length, match_pos = longest(0, chain, 0)
    while True:
        chain = insert(pos + 1)
        next_length, next_pos = longest(pos + 1, chain, match_length)
        if match_length >= next_length and match_length >= 3:
            distance = pos - match_pos
            encoded = (distance << 4) | (match_length - 2)
            tokens.append(("match", struct.pack("<H", encoded)))
            pos += 2
            for _ in range(match_length - 2):
                insert(pos)
                pos += 1
            if pos >= length - 1:
                if pos < length:
                    tokens.append(("raw", source[pos : pos + 1]))
                break
            chain = insert(pos)
            match_length, match_pos = longest(pos, chain, 0)
        else:
            tokens.append(("raw", source[pos : pos + 1]))
            pos += 1
            if pos >= length:
                break
            match_length, match_pos = next_length, next_pos
    return _pack(tokens)


def _pack(tokens) -> bytes:
    result = bytearray()
    for start in range(0, len(tokens), 8):
        group = tokens[start : start + 8]
        flag = 0
        payload = bytearray()
        for index, (kind, value) in enumerate(group):
            if kind == "raw":
                flag |= 1 << index
            payload.extend(value)
        result.append(flag)
        result.extend(payload)
    # Compress::Flush appends TmpData even just after a full eight-token group;
    # Reset leaves that container holding one zero flag byte.
    if not tokens or len(tokens) % 8 == 0:
        result.append(0)
    return bytes(result)


def compress_kprl(uncompressed: bytes) -> bytes:
    if uncompressed[:4] != b"KPRL":
        raise ValueError("RealLive compression requires an uncompressed KPRL file")
    offset = struct.unpack_from("<I", uncompressed, 0x20)[0]
    code = uncompressed[offset:]
    packed = lz77_compress(code)
    block = apply_mask(struct.pack("<II", len(packed) + 8, len(code)) + packed)
    header = bytearray(uncompressed[:offset])
    struct.pack_into("<I", header, 0, 0x1D0)
    struct.pack_into("<I", header, 0x28, len(block))
    return bytes(header) + block


def mask_kp2k(uncompressed: bytes) -> bytes:
    """AVG2000 has no LZ77 stage; bytecodeGen.ml only masks its code block."""
    if uncompressed[:4] != b"KP2K":
        raise ValueError("AVG2000 masking requires an uncompressed KP2K file")
    count = struct.unpack_from("<I", uncompressed, 0x20)[0]
    offset = 0x1CC + count * 4
    header = bytearray(uncompressed[:offset])
    struct.pack_into("<I", header, 0, 0x1CC)
    return bytes(header) + apply_mask(uncompressed[offset:])
