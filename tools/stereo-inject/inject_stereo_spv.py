"""给官方 .spv 就地注入立体视差（SPIR-V 汇编层改文本，再用 spirv-as 汇编回去）。

为什么要在 SPIR-V 层做：游戏运行时还会从模板现场生成约 7,300 个着色器程序，提取阶段拿不到它们的
SASS，翻译器覆盖不到。这些官方 .spv 是现成的，直接在汇编上插入算术即可，且完全绕开 glslc 的常量折叠。

注入内容（顶点着色器插在每个入口函数末尾的 OpReturn 之前；网格着色器插在每个 gl_Position 的
OpStore 处）：
    t = (w > 1.25) ? (1 - w / STEREO_CONV) : 0     透视几何：位移随深度反比、有界
                                                    （NDC 位移 = SEP * (1/w - 1/CONV)）
        (w >= 500 时 t = 0：HUD 两眼一致)
    x += float(STEREO_EYE) * STEREO_SEP * t
三个 SpecId 900/901/902 的 OpSpecConstant 默认值 1 / 0.02 / 20，运行时 vk_spirv_patch.c 的
spirv_stereo() 按眼改成 -1 / +1（单色时改成 0）。

旧变体 x += SEP*(w - CONV) 见 inject_stereo_spv_unbounded.py：位移随深度线性增长、无上界，
近距离几何被剪切得厉害，影子/明暗会看起来像从相反方向打过来（两眼互为镜像）。不要再用那个。
"""
import argparse
import os
import pathlib
import struct
import subprocess

SPEC = """               OpDecorate {eye} SpecId 900
               OpDecorate {sep} SpecId 901
               OpDecorate {conv} SpecId 902
"""
SCONST = """{eye} = OpSpecConstant %int 1
{sep} = OpSpecConstant %float 0.02
{conv} = OpSpecConstant %float 20
"""
GUARD = """{bline}{near} = OpConstant %float 1.25
{far} = OpConstant %float 500
{f0} = OpConstant %float 0
{f1} = OpConstant %float 1
"""


def dis(spv, out):
    subprocess.run(["spirv-dis", spv, "-o", out], check=True)


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def find_position_var(lines):
    """返回 (位置输出变量的 id, 是否 gl_PerVertex 结构体成员 0)。"""
    block_types = set()
    for ln in lines:
        s = ln.strip()
        if s.startswith("OpMemberDecorate") and "BuiltIn Position" in s:
            block_types.add(s.split()[1].lstrip("%"))
    if block_types:
        for ln in lines:
            s = ln.strip()
            if "= OpVariable" not in s or " Output" not in s:
                continue
            toks = s.replace("=", " ").split()
            ptr = toks[2]
            for b in block_types:
                if b in ptr:
                    return toks[0], True
    for ln in lines:
        s = ln.strip()
        if s.startswith("OpDecorate") and "BuiltIn Position" in s:
            return s.split()[1], False
    return None, False


def max_id(lines, floor=0):
    m = floor
    for ln in lines:
        for tok in ln.replace("(", " ").replace(")", " ").split():
            t = tok.strip(",")
            if t.startswith("%") and t[1:].isdigit():
                m = max(m, int(t[1:]))
    return m


def vec4_name(lines):
    for ln in lines:
        s = ln.strip()
        if "= OpTypeVector %float 4" in s:
            return s.split()[0]
    return "%v4float"


def mesh_position_chains(lines):
    """gl_MeshVerticesEXT[i].gl_Position 的访问链：返回指向位置成员的 OpAccessChain 结果 id 集合。"""
    structs = set()
    for ln in lines:
        s = ln.strip()
        if s.startswith("OpMemberDecorate") and "BuiltIn Position" in s and s.split()[2] == "0":
            structs.add(s.split()[1])
    if not structs:
        return set()
    arrs = {ln.strip().split()[0] for ln in lines if "= OpTypeArray" in ln and any(st in ln for st in structs)}
    if not arrs:
        return set()
    vars_ = set()
    for ln in lines:
        s = ln.strip()
        if "= OpVariable" in s and " Output" in s:
            toks = s.replace("=", " ").split()
            if any(a.strip("%") in toks[2] for a in arrs):
                vars_.add(toks[0])
    if not vars_:
        return set()
    chains = set()
    for ln in lines:
        s = ln.strip()
        if "OpAccessChain" in s or "OpInBoundsAccessChain" in s:
            toks = s.split()
            if len(toks) > 4 and toks[4] in vars_:
                chains.add(toks[0])
    return chains


def inject_mesh(lines, ids, vec4, entry):
    """网格着色器：改写每个写 gl_Position 的 OpStore，x 加上视差。"""
    chains = mesh_position_chains(lines)
    if not chains:
        return None, "mesh: no position output"
    stores = [i for i, ln in enumerate(lines)
              if ln.strip().startswith("OpStore") and ln.split()[1] in chains]
    if not stores:
        return None, "mesh: no position store"

    # eye 的浮点化定义在入口函数第一个块的变量声明之后（无条件执行，各处都能用）
    entry_fn = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if "= OpFunction " in s and s.split()[0] == entry:
            entry_fn = i
            break
    if entry_fn is None:
        entry_fn = next(i for i, ln in enumerate(lines) if "= OpFunction " in ln)
    block = next(i for i in range(entry_fn, len(lines)) if "OpLabel" in lines[i])
    at = block + 1
    while at < len(lines) and ("OpVariable" in lines[at] or not lines[at].strip()):
        at += 1
    lines.insert(at, "    %s = OpConvertSToF %%float %s" % (ids["eyef"], ids["eye"]))
    stores = [i + 1 if i >= at else i for i in stores]

    nxt = max_id(lines) + 1
    out = []
    done = 0
    for i, ln in enumerate(lines):
        if i not in stores:
            out.append(ln)
            continue
        toks = ln.split()
        ptr, val = toks[1], toks[2]
        n = ["%d" % (nxt + k) for k in range(14)]
        nxt += 14
        x, w, g1, d1, t1, l1, m, t2, d2, d3, nx, v2, d4, _sp = ["%%%s" % t for t in n]
        out.extend([
            "    %s = OpCompositeExtract %%float %s 0" % (x, val),
            "    %s = OpCompositeExtract %%float %s 3" % (w, val),
            "    %s = OpFOrdGreaterThan %%bool %s %s" % (g1, w, ids["near"]),
            "    %s = OpFDiv %%float %s %s" % (d4, w, ids["conv"]),
            "    %s = OpFSub %%float %s %s" % (d1, ids["f1"], d4),
            "    %s = OpSelect %%float %s %s %s" % (t1, g1, d1, ids["f0"]),
            "    %s = OpFOrdLessThan %%bool %s %s" % (l1, w, ids["far"]),
            "    %s = OpSelect %%float %s %s %s" % (m, l1, ids["f1"], ids["f0"]),
            "    %s = OpFMul %%float %s %s" % (t2, t1, m),
            "    %s = OpFMul %%float %s %s" % (d2, t2, ids["sep"]),
            "    %s = OpFMul %%float %s %s" % (d3, d2, ids["eyef"]),
            "    %s = OpFAdd %%float %s %s" % (nx, x, d3),
            "    %s = OpCompositeInsert %s %s %s 0" % (v2, vec4, nx, val),
            "               OpStore %s %s" % (ptr, v2),
        ])
        done += 1
    if not done:
        return None, "mesh: no position store"
    return "\n".join(out), None


def inject(text, base=None):
    lines = text.split("\n")
    pos, is_block = find_position_var(lines)
    if not pos:
        return None, "no position variable"

    maxid = max_id(lines, (base - 1) if base else 0)
    names = ["eye", "sep", "conv", "x", "w", "px", "pw", "vx", "vw", "d1", "d2", "d3", "d4",
             "nx", "eyef", "near", "far", "f0", "f1", "g1", "l1", "ok", "m", "b", "t1", "t2"]
    ids = {k: "%%%d" % (maxid + 1 + i) for i, k in enumerate(names)}

    btype = None
    for ln in lines:
        t = ln.strip()
        if "= OpTypeBool" in t:
            btype = t.split()[0]
            break
    if btype:
        ids["b"] = btype

    first_func = next(i for i, ln in enumerate(lines) if "= OpFunction " in ln and "OpFunctionEnd" not in ln)
    sconst = SCONST.format(eye=ids["eye"], sep=ids["sep"], conv=ids["conv"])
    sdecor = SPEC.format(eye=ids["eye"], sep=ids["sep"], conv=ids["conv"])
    deco_idx = next((i for i, ln in enumerate(lines) if ln.strip().startswith("OpDecorate")), first_func)
    lines.insert(deco_idx, sdecor.rstrip("\n"))
    first_func = next(i for i, ln in enumerate(lines) if "= OpFunction " in ln and "OpFunctionEnd" not in ln)
    bline = "" if btype else "{b} = OpTypeBool\n".format(b=ids["b"])
    guard = GUARD.format(bline=bline, near=ids["near"], far=ids["far"], f0=ids["f0"], f1=ids["f1"])
    lines.insert(first_func, sconst.rstrip("\n") + "\n" + guard.rstrip("\n"))

    entry = None
    mesh = False
    for ln in lines:
        s = ln.strip()
        if s.startswith("OpEntryPoint Vertex"):
            entry = s.split()[2]
            break
        if s.startswith("OpEntryPoint MeshEXT"):
            entry = s.split()[2]
            mesh = True
            break
    if not entry:
        return None, "not a vertex stage"
    if mesh:
        return inject_mesh(lines, ids, vec4_name(lines), entry)

    start = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if "= OpFunction" in s and s.split()[0] == entry:
            start = i
            break
    if start is None:
        return None, "entry not found"
    end = next(i for i in range(start, len(lines)) if lines[i].strip().startswith("OpFunctionEnd"))
    ret = max(i for i in range(start, end) if lines[i].strip().startswith("OpReturn"))

    if is_block:
        px = "{id} = OpAccessChain %_ptr_Output_float {pos} %int_0 %uint_0".format(id=ids["px"], pos=pos)
        pw = "{id} = OpAccessChain %_ptr_Output_float {pos} %int_0 %uint_3".format(id=ids["pw"], pos=pos)
    else:
        px = "{id} = OpAccessChain %_ptr_Output_float {pos} %uint_0".format(id=ids["px"], pos=pos)
        pw = "{id} = OpAccessChain %_ptr_Output_float {pos} %uint_3".format(id=ids["pw"], pos=pos)
    body = [
        px, pw,
        "{id} = OpLoad %float {px}".format(id=ids["vx"], px=ids["px"]),
        "{id} = OpLoad %float {pw}".format(id=ids["vw"], pw=ids["pw"]),
        "{id} = OpConvertSToF %float {eye}".format(id=ids["eyef"], eye=ids["eye"]),
        # t = (w > 1.25) ? (w - CONV) : 0      -- w == 1 是正交投影（阴影贴图、环境探针、精灵）：不位移。
        #   那里的相机横移在裁剪空间是常量，不随 w 缩放。
        "{id} = OpFOrdGreaterThan {b} {vw} {near}".format(id=ids["g1"], b=ids["b"], vw=ids["vw"], near=ids["near"]),
        "{id} = OpFDiv %float {vw} {conv}".format(id=ids["d4"], vw=ids["vw"], conv=ids["conv"]),
        "{id} = OpFSub %float {f1} {d4}".format(id=ids["d1"], f1=ids["f1"], d4=ids["d4"]),
        #   正交投影（w<=1.25）一律不位移：阴影贴图和环境探针都是正交，给它常量视差等于把整个光源视角
        #   推走，影子会相对物体在左右眼里反向偏移——看起来就是"两个不同光源"。
        "{id} = OpSelect %float {g1} {d1} {f0}".format(id=ids["t1"], g1=ids["g1"], d1=ids["d1"], f0=ids["f0"]),
        # HUD（w 很大）两眼一致
        "{id} = OpFOrdLessThan {b} {vw} {far}".format(id=ids["l1"], b=ids["b"], vw=ids["vw"], far=ids["far"]),
        "{id} = OpSelect %float {l1} {f1} {f0}".format(id=ids["m"], l1=ids["l1"], f1=ids["f1"], f0=ids["f0"]),
        "{id} = OpFMul %float {t1} {m}".format(id=ids["t2"], t1=ids["t1"], m=ids["m"]),
        "{id} = OpFMul %float {t2} {sep}".format(id=ids["d2"], t2=ids["t2"], sep=ids["sep"]),
        "{id} = OpFMul %float {d2} {eyef}".format(id=ids["d3"], d2=ids["d2"], eyef=ids["eyef"]),
        "{id} = OpFAdd %float {vx} {d3}".format(id=ids["nx"], vx=ids["vx"], d3=ids["d3"]),
        "OpStore {px} {nx}".format(px=ids["px"], nx=ids["nx"]),
    ]
    for j, b in enumerate(body):
        lines.insert(ret + j, "        " + b)
    return "\n".join(lines), None


def one(f, dst):
    asm = dst / (f.stem + ".spvasm")
    dis(str(f), str(asm))
    text = asm.read_text()
    bound = struct.unpack("<I", f.read_bytes()[12:16])[0]
    new, why = inject(text, bound)
    if not new:
        asm.unlink(missing_ok=True)
        return "skip", why
    asm.write_text(new)
    out = dst / f.name
    r = run(["spirv-as", str(asm), "-o", str(out), "--target-env", "vulkan1.3"])
    if r.returncode != 0:
        return "assemble", r.stderr.strip().split("\n")[0][:70]
    v = run(["spirv-val", str(out), "--target-env", "vulkan1.3"])
    if v.returncode != 0:
        return "validate", v.stderr.strip().split("\n")[0][:70]
    asm.unlink(missing_ok=True)
    return "ok", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    src, dst = pathlib.Path(a.src), pathlib.Path(a.dst)
    dst.mkdir(parents=True, exist_ok=True)
    files = sorted(src.glob("*.spv"))
    if a.limit:
        files = files[: a.limit]
    cnt = {"ok": 0, "skip": 0, "assemble": 0, "validate": 0}
    reasons = {}
    for f in files:
        kind, why = one(f, dst)
        cnt[kind] += 1
        if why:
            reasons["%s: %s" % (kind, why)] = reasons.get("%s: %s" % (kind, why), 0) + 1
    print("ok %d / skip %d / assemble-fail %d / validate-fail %d（共 %d）"
          % (cnt["ok"], cnt["skip"], cnt["assemble"], cnt["validate"], len(files)))
    for k, v in sorted(reasons.items(), key=lambda t: -t[1])[:10]:
        print("  %-60s %d" % (k, v))


if __name__ == "__main__":
    main()
