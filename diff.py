import os
import filecmp

def diff_directories(dir1, dir2):
    # Compare the directory trees
    comparison = filecmp.dircmp(dir1, dir2)

    # Files that differ between the two directories
    diff_files = comparison.diff_files

    # Recursively check subdirectories
    for subdir in comparison.common_dirs:
        sub_diff_files = diff_directories(
            os.path.join(dir1, subdir),
            os.path.join(dir2, subdir)
        )
        diff_files.extend([os.path.join(subdir, f) for f in sub_diff_files])

    return diff_files

if __name__ == "__main__":
    dir1 = "librespot_dm"
    dir2 = "librespot"

    differences = diff_directories(dir1, dir2)
    if differences:
        print("Files that differ:")
        for file in differences:
            print(file)
    else:
        print("No differing files found.")