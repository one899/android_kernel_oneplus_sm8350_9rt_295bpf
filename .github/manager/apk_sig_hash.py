import sys, struct, hashlib

def lp(data, pos, end):
    n = struct.unpack_from('<I', data, pos)[0]; pos += 4
    if pos + n > end: raise SystemExit('bad length prefix')
    return pos, pos + n

def extract_cert(data, pos, block_end):
    pos, signers_end = lp(data, pos, block_end)
    pos, signer_end  = lp(data, pos, signers_end)
    pos, sd_end      = lp(data, pos, signer_end)
    pos, digests_end = lp(data, pos, sd_end)
    pos = digests_end
    pos, certs_end = lp(data, pos, sd_end)
    size = struct.unpack_from('<I', data, pos)[0]; pos += 4
    if pos + size > certs_end: raise SystemExit('bad cert size')
    return size, data[pos:pos+size]

def main(path):
    data = open(path, 'rb').read()
    eocd = data.rfind(b'PK\x05\x06')
    if eocd < 0: raise SystemExit('EOCD not found')
    cd_size, cd_off = struct.unpack_from('<II', data, eocd + 12)
    if cd_off < 0x20 or data[cd_off-16:cd_off] != b'APK Sig Block 42':
        raise SystemExit('no APK signing block')
    size_of_block = struct.unpack_from('<Q', data, cd_off - 24)[0]
    block_start = cd_off - size_of_block - 8
    if struct.unpack_from('<Q', data, block_start)[0] != size_of_block:
        raise SystemExit('block size mismatch')
    pos = block_start + 8
    pairs_end = cd_off - 24
    while pos < pairs_end:
        pair_len = struct.unpack_from('<Q', data, pos)[0]; pos += 8
        pid = struct.unpack_from('<I', data, pos)[0]
        pair_end = pos + pair_len
        if pid == 0x7109871a:
            size, cert = extract_cert(data, pos + 4, pair_end)
            print("SIZE=0x%x" % size)
            print("HASH=%s" % hashlib.sha256(cert).hexdigest().upper())
            print("HASH_LOWER=%s" % hashlib.sha256(cert).hexdigest())
            return
        pos = pair_end
    raise SystemExit('no v2 signature block')

if __name__ == '__main__':
    main(sys.argv[1])