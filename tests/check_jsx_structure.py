"""Structural integrity check for index.html's inline Babel/JSX block.

No node/babel dependency (this is a Python project). It scans the
<script type="text/babel"> block, skips string/template/comment content, and
reports the bracket balance for () {} []. A blank-screen JSX edit error almost
always shows up as a bracket imbalance here. Compare the printed balances before
and after an edit — they must stay identical (and ideally net 0).
Run:  python tests/check_jsx_structure.py
"""
import re
import sys

src = open("index.html", encoding="utf-8").read()
m = re.search(r'<script type="text/babel">(.*?)</script>', src, re.S)
if not m:
    print("FAIL: no babel script block found"); sys.exit(2)
code = m.group(1)

bal = {"()": 0, "{}": 0, "[]": 0}
i, n = 0, len(code)
state = "code"  # code | sq | dq | tpl | line | block
depth_stack = []  # template-literal ${ } nesting
while i < n:
    c = code[i]
    nxt = code[i + 1] if i + 1 < n else ""
    if state == "code":
        if c == "/" and nxt == "/":
            state = "line"; i += 2; continue
        if c == "/" and nxt == "*":
            state = "block"; i += 2; continue
        if c == "'":
            state = "sq"; i += 1; continue
        if c == '"':
            state = "dq"; i += 1; continue
        if c == "`":
            state = "tpl"; i += 1; continue
        if c == "(":
            bal["()"] += 1
        elif c == ")":
            bal["()"] -= 1
        elif c == "{":
            bal["{}"] += 1
        elif c == "}":
            if depth_stack and depth_stack[-1] == "tpl_expr":
                depth_stack.pop(); state = "tpl"; i += 1; continue
            bal["{}"] -= 1
        elif c == "[":
            bal["[]"] += 1
        elif c == "]":
            bal["[]"] -= 1
        i += 1
    elif state == "sq":
        if c == "\\":
            i += 2; continue
        if c == "'":
            state = "code"
        i += 1
    elif state == "dq":
        if c == "\\":
            i += 2; continue
        if c == '"':
            state = "code"
        i += 1
    elif state == "tpl":
        if c == "\\":
            i += 2; continue
        if c == "`":
            state = "code"; i += 1; continue
        if c == "$" and nxt == "{":
            depth_stack.append("tpl_expr"); state = "code"; i += 2; continue
        i += 1
    elif state == "line":
        if c == "\n":
            state = "code"
        i += 1
    elif state == "block":
        if c == "*" and nxt == "/":
            state = "code"; i += 2; continue
        i += 1

# {} and [] are reliable JSX-integrity signals (always code-state, no JSX-text
# noise). () carries constant noise from regex/JSX-text parens; pinned to a
# baseline so edits must not change it.
PAREN_BASELINE = -3
print("babel block chars:", len(code))
print("bracket balance:", bal, "| state at EOF:", state)
ok = bal["{}"] == 0 and bal["[]"] == 0 and bal["()"] == PAREN_BASELINE and state == "code"
print("RESULT:", "BALANCED" if ok else "IMBALANCE (edit broke JSX structure)")
sys.exit(0 if ok else 1)
