"""Run with the wheel environment's Python -I; no checkout imports allowed."""
import importlib
import os
import pkgutil
import sys
import tempfile
from contextlib import chdir
from pathlib import Path


def main():
    import scion_omaha_bots

    package_root = Path(scion_omaha_bots.__file__).resolve().parent
    assert package_root.is_relative_to(Path(sys.prefix).resolve())
    assert 'site-packages' in package_root.parts
    assert 'yfinance' not in sys.modules
    with tempfile.TemporaryDirectory() as directory, chdir(directory):
        os.environ['STOCK_ANALYSIS_STATE_ROOT'] = directory
        os.environ['STOCK_ANALYSIS_OUTPUTS_ROOT'] = str(Path(directory) / 'reports')
        for runner in (scion_omaha_bots.scion_main, scion_omaha_bots.omaha_main):
            try:
                runner(['--help'])
            except SystemExit as exc:
                assert exc.code == 0
            assert runner(['portfolio']) == 0
        for info in pkgutil.walk_packages(scion_omaha_bots.__path__, 'scion_omaha_bots.'):
            module = importlib.import_module(info.name)
            assert Path(module.__file__).resolve().is_relative_to(package_root)
        from scion_omaha_bots.portfolio import ScionPortfolioManager
        from scion_omaha_bots.buffett_portfolio import BuffettPortfolioManager

        for cls, name in ((ScionPortfolioManager, 'scion'), (BuffettPortfolioManager, 'omaha')):
            path = str(Path(directory) / f'{name}.json')
            manager = cls(capital=10000, portfolio_file=path)
            manager.save_state()
            assert cls(portfolio_file=path).cash == 10000
    print('Installed-wheel smoke passed: both CLIs, all runtime imports, offline state round trips.')


if __name__ == '__main__':
    main()
