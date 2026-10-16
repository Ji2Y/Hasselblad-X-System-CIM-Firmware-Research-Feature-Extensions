"""Read embedded Qt v3 RCC resources from a supplied ELF, without device access.

Callers must select their own paths and validate their firmware input hashes.
Returns the exact node address for scoped offline replacements.
"""
import struct
import zlib
from elftools.elf.elffile import ELFFile


def resources(elf):
    groups = []
    for suffix in ('struct', 'name', 'data'):
        name = 'qt_resource_' + suffix
        groups.append(sorted((s for s in elf.get_section_by_name('.symtab').iter_symbols()
                              if s.name == '_ZL' + str(len(name)) + name),
                             key=lambda s: s['st_value']))
    assert len(groups[0]) == len(groups[1]) == len(groups[2])
    sections = {}

    def blob(symbol):
        ix = symbol['st_shndx']
        if ix not in sections:
            sec = elf.get_section(ix)
            sections[ix] = (sec['sh_addr'], sec.data())
        start, data = sections[ix]
        offset = symbol['st_value'] - start
        return data[offset:offset + symbol['st_size']]

    for tree_sym, name_sym, data_sym in zip(*groups):
        tree, names, data = map(blob, (tree_sym, name_sym, data_sym))
        assert len(tree) % 22 == 0

        def walk(index, parent):
            at = index * 22
            no, flags = struct.unpack_from('>IH', tree, at)
            if index:
                length = struct.unpack_from('>H', names, no)[0]
                name = names[no + 6:no + 6 + length * 2].decode('utf-16be')
                path = parent + '/' + name
            else:
                path = ''
            if flags & 2:
                count, first = struct.unpack_from('>II', tree, at + 6)
                assert first + count <= len(tree) // 22
                for child in range(first, first + count):
                    yield from walk(child, path)
            else:
                offset = struct.unpack_from('>I', tree, at + 10)[0]
                length = struct.unpack_from('>I', data, offset)[0]
                encoded = data[offset + 4:offset + 4 + length]
                assert len(encoded) == length
                if flags & 1:
                    expected = struct.unpack_from('>I', encoded)[0]
                    content = zlib.decompress(encoded[4:])
                    assert len(content) == expected
                elif flags & 4:
                    content = None  # Never treat zstd as uncompressed data.
                else:
                    content = encoded
                yield dict(path=path, content=content, flags=flags,
                           nodeVA=tree_sym['st_value'] + at,
                           dataBaseVA=data_sym['st_value'], dataOffset=offset)
        yield from walk(0, '')
