from folder_structure.some_globals import SOME_GLOBAL_VARIABLE
from folder_structure.subfolder_to_build.some_function import print_and_return_global_variable


def test_normal_execution():
    variable = print_and_return_global_variable()
    assert variable == SOME_GLOBAL_VARIABLE