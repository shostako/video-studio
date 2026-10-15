"""検査の足場が動いていることだけを確かめる。純関数のテストはここへ足していく。"""
import importlib


def test_lib_importable():
    lib = importlib.import_module("lib")
    assert hasattr(lib, "Proj")
