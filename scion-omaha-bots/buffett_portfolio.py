"""Compatibility entry point; runtime lives in the installed package."""
import sys

if __name__ == "__main__":
    import runpy

    runpy.run_module("scion_omaha_bots.buffett_portfolio", run_name="__main__")
else:
    from scion_omaha_bots import buffett_portfolio as _module

    sys.modules[__name__] = _module
