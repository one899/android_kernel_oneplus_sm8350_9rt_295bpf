#!/usr/bin/env python3
"""从 /proc/modules 隐藏指定模块（仅对非 CAP_SYS_ADMIN 进程）"""
import sys

MODNAME = "kernelsu"
path = sys.argv[1] if len(sys.argv) > 1 else "kernel/module.c"
src = open(path, encoding="utf-8", errors="surrogateescape").read()

needle = "static int m_show(struct seq_file *m, void *p)\n{\n"
marker = "capable(CAP_SYS_ADMIN)"

if marker in src and MODNAME in src.split("m_show")[1][:800]:
    print("already patched, skip")
    sys.exit(0)

if needle not in src:
    print("!! m_show signature not found - kernel source differs")
    sys.exit(0)

inject = (
    '\t/* hidden module: 普通进程看不到 */\n'
    '\tif (!capable(CAP_SYS_ADMIN) && strcmp(mod->name, "%s") == 0)\n'
    '\t\treturn 0;\n' % MODNAME
)
src = src.replace(needle, needle + inject, 1)
open(path, "w", encoding="utf-8", errors="surrogateescape").write(src)
print("patched m_show in", path)