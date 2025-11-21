if True:
    import sysappend

    sysappend.all()

from folder_structure.utility_folder.some_utility import print_something
from some_globals import SOME_GLOBAL_VARIABLE


def print_and_return_global_variable():
    print_something(SOME_GLOBAL_VARIABLE)
    return SOME_GLOBAL_VARIABLE


print_and_return_global_variable()
