"""边界面板：同一个插件在同一个 hook 上有多个实现时，「谁实现了这个 hook」在
register / unregister / subset_hook_caller / get_hookcallers 四个入口给出的答案
是否一致；以及 subset_hook_caller 对「当前没有该 hook 实现的插件」返回的对象，
在该插件之后注册了实现之后的表现。

用法（在仓库根目录）：
    timeout 120 env PYTHONPATH=src .venv/bin/python <此文件>
"""

from pluggy import HookimplMarker
from pluggy import HookspecMarker
from pluggy import PluginManager


hookspec = HookspecMarker("example")
hookimpl = HookimplMarker("example")

OUT: list[str] = []


def make_pm():
    pm = PluginManager("example")

    class Hooks:
        @hookspec
        def he_method1(self, arg):
            raise NotImplementedError()

        @hookspec
        def he_method2(self, arg):
            raise NotImplementedError()

    pm.add_hookspecs(Hooks)
    return pm


class TwoImplsOneHook:
    """同一插件在 he_method1 上有两个实现：一个按函数名，一个按 specname。"""

    @hookimpl
    def he_method1(self, arg):
        OUT.append(f"plain:{arg}")

    @hookimpl(specname="he_method1")
    def under_other_name(self, arg):
        OUT.append(f"alias:{arg}")

    @hookimpl
    def he_method2(self, arg):
        OUT.append(f"m2:{arg}")


class SpecNameOnly:
    """只有 specname 形式的实现，插件对象上没有 he_method1 这个属性。"""

    @hookimpl(specname="he_method1")
    def totally_different(self, arg):
        OUT.append(f"spec-only:{arg}")


class Plain:
    @hookimpl
    def he_method1(self, arg):
        OUT.append(f"plain-plugin:{arg}")


class LateImpl:
    @hookimpl
    def he_method1(self, arg):
        OUT.append(f"late:{arg}")


class NoAttrAtAll:
    """对象上连 he_method1 这个属性都没有，注册前才加上。"""


CHECKS: list[tuple[str, object]] = []


def check(label):
    def deco(fn):
        CHECKS.append((label, fn))
        return fn

    return deco


@check("L1 unregister 后，该插件在该 hook 上的实现全部消失")
def _l1():
    pm = make_pm()
    p = TwoImplsOneHook()
    pm.register(p)
    pm.hook.he_method1(arg=1)
    pm.unregister(p)
    OUT.clear()
    pm.hook.he_method1(arg=2)
    return OUT == []


@check("L2 get_hookcallers 对同一个 caller 只列一次（顺序 he_method1, he_method2）")
def _l2():
    pm = make_pm()
    p = TwoImplsOneHook()
    pm.register(p)
    callers = pm.get_hookcallers(p)
    assert callers is not None
    return [c.name for c in callers] == ["he_method1", "he_method2"]


@check("L3 subset_hook_caller 能剔除只有 specname 实现的插件")
def _l3():
    pm = make_pm()
    spec_only = SpecNameOnly()
    pm.register(spec_only)
    pm.register(Plain())
    hc = pm.subset_hook_caller("he_method1", [spec_only])
    OUT.clear()
    hc(arg=3)
    return OUT == ["plain-plugin:3"]


@check("L4 剔除集对「当时尚未注册的实现」也生效（代理语义是动态的）")
def _l4():
    pm = make_pm()
    late = LateImpl()
    pm.register(Plain())
    hc = pm.subset_hook_caller("he_method1", [late])
    pm.register(late)
    OUT.clear()
    hc(arg=4)
    return OUT == ["plain-plugin:4"]


@check("L5 请求剔除的插件当前没有该属性/实现时，返回对象仍带剔除语义")
def _l5():
    pm = make_pm()
    later = NoAttrAtAll()
    pm.register(Plain())
    hc = pm.subset_hook_caller("he_method1", [later])
    setattr(later, "he_method1", hookimpl(lambda arg: OUT.append(f"late2:{arg}")))
    pm.register(later, name="later")
    OUT.clear()
    hc(arg=5)
    return OUT == ["plain-plugin:5"]


@check("L6 现成场景回归：普通实现的剔除 + 原 caller 不受影响")
def _l6():
    pm = make_pm()
    p1, p2 = Plain(), TwoImplsOneHook()
    pm.register(p1)
    pm.register(p2)
    OUT.clear()
    pm.hook.he_method1(arg=1)
    first = sorted(OUT)
    OUT.clear()
    hc = pm.subset_hook_caller("he_method1", [p2])
    hc(arg=2)
    subset_out = list(OUT)
    OUT.clear()
    pm.hook.he_method1(arg=3)
    after = sorted(OUT)
    return (
        first == ["alias:1", "plain-plugin:1", "plain:1"]
        and subset_out == ["plain-plugin:2"]
        and after == ["alias:3", "plain-plugin:3", "plain:3"]
    )


@check("L7 现成场景回归：historic hook + subset")
def _l7():
    pm = PluginManager("example")

    class Hooks:
        @hookspec(historic=True)
        def he_h(self, arg):
            raise NotImplementedError()

    pm.add_hookspecs(Hooks)

    class A:
        @hookimpl
        def he_h(self, arg):
            OUT.append(f"a:{arg}")

    class B:
        @hookimpl
        def he_h(self, arg):
            OUT.append(f"b:{arg}")

    a = A()
    pm.register(a)
    OUT.clear()
    hc = pm.subset_hook_caller("he_h", [a])
    hc.call_historic(kwargs=dict(arg=1))
    pm.register(B())
    pm.register(A())
    return OUT == ["b:1", "a:1"]


@check("L8 双实现插件：一次调用里两个实现各跑一次，顺序稳定")
def _l8():
    pm = make_pm()
    pm.register(TwoImplsOneHook())
    OUT.clear()
    pm.hook.he_method1(arg=5)
    return OUT == ["alias:5", "plain:5"]


@check("L9 现成场景回归：普通插件的 get_hookcallers 顺序与未注册插件返回 None")
def _l9():
    pm = make_pm()

    class BothHooks:
        @hookimpl
        def he_method1(self, arg):  # pragma: no cover
            OUT.append(f"both1:{arg}")

        @hookimpl
        def he_method2(self, arg):  # pragma: no cover
            OUT.append(f"both2:{arg}")

    p1 = BothHooks()
    p2 = Plain()
    p3 = SpecNameOnly()
    pm.register(p1)
    pm.register(p2)
    pm.register(p3)
    c1 = pm.get_hookcallers(p1)
    c2 = pm.get_hookcallers(p2)
    c3 = pm.get_hookcallers(p3)
    assert c1 is not None and c2 is not None and c3 is not None
    return (
        [c.name for c in c1] == ["he_method1", "he_method2"]
        and c1[0] is c2[0] is c3[0]
        and pm.get_hookcallers(object()) is None
    )


print(f"panel: {len(CHECKS)} checks")
passed = 0
for label, fn in CHECKS:
    OUT.clear()
    try:
        ok = bool(fn())
        detail = ""
    except Exception as exc:  # noqa: BLE001
        ok = False
        detail = f" (raised {type(exc).__name__}: {exc})"
    passed += ok
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else detail))
print(f"SUMMARY {passed}/{len(CHECKS)}")
