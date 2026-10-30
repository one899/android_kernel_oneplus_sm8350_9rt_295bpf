#!/usr/bin/env python3
"""从 /proc/modules 隐藏指定模块（仅对非 CAP_SYS_ADMIN 进程）"""
import sys

MODNAME = "kernelsu"
path = sys.argv[1] if len(sys.argv) > 1 else "kernel/module.c"
src = open(path, encoding="utf-8", errors="surrogateescape").read()

if 'strcmp(mod->name, "%s")' % MODNAME in src:
    print("already patched, skip")
    sys.exit(0)

func = "static int m_show(struct seq_file *m, void *p)\n{\n"
pos = src.find(func)
if pos < 0:
    print("!! m_show not found - kernel source differs")
    sys.exit(0)

# 在 m_show 函数体内找到 mod 的声明语句，插在它后面
body_start = pos + len(func)
decl = "\tstruct module *mod = list_entry(p, struct module, list);\n"
dpos = src.find(decl, body_start, body_start + 400)
if dpos < 0:
    print("!! mod declaration not found in m_show")
    sys.exit(0)

inject = (
    '\t/* hidden: 非特权进程看不到 */\n'
    '\tif (!capable(CAP_SYS_ADMIN) && strcmp(mod->name, "%s") == 0)\n'
    '\t\treturn 0;\n' % MODNAME
)
ins = dpos + len(decl)
src = src[:ins] + inject + src[ins:]
open(path, "w", encoding="utf-8", errors="surrogateescape").write(src)
print("patched m_show (after mod decl)")