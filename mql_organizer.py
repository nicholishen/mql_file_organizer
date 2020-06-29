"""
2020, nicholishen

Requires:
    Python >= 3.6
    pandas
    openpyxl
    chardet

    pip install -U pandas ujson openpyxl chardet


What it is:
    A script that gathers all your MQL files and organizes them together and provides detailed reports in JSON and Excel.

How it works:
    The script recursively searches the defined directory for MQL files (default is root drive). When a target file is
    encountered its checksum is generated and the file gets mapped to the checksum. If another file is discovered in a
    different location with the same checksum and same filename then only one version of the file will be copied over to
    the new (organized) directory. If a file is discovered with the same checksum and a different filename then both files
    will be copied, and a log-entry will be added to the report so you can decide which version to keep. If more than
    one file shares the same filename but a different checksum, then the file is still copied but renamed. For example
    if a test.mq4 file is found in two separate directories and don’t have the same checksum it will result in test.mq4
    and test(1).mq4. In this instance a log entry will be added to the report under “Diff files”.  MQL files that are
    discovered in a directory that isn’t a typical MQL path (eg. Downloads) will be placed in a new subdirectory
    titled “UNORGANIZED”. Reports are saved in the root directory of the newly organized files.

Reporting:
    A JSON dump is generated with the following properties:

    time_completed: datetime that the script was run
    total_files: The total number of files in the directory
    search_path: The path of the most recent search
    save_path: The path where the organized files were copied to
    extensions: An array of extensions that were searched
    diff_files: An array of paths to files discovered with the same name in the same directory with a different checksum
    manifest: An array of details for all files in the newly organized directory.
    Shape of manifest:
    [
        {
            "name": "ProZigZag.mqh",
            "extension": ".mqh",
            "is_src": true,
            "file_size": 24046,
            "time_modified": "2017-11-08 06:22:32",
            "path": "C:\\Users\\user\\Desktop\\MQL_FILES\\MQL4\\Include\\Indicators\\ProZigZag.mqh",
            "checksum": "7bbecd93b992d4b336a4c7a63c18081c0dfasdfasd514ada720b12f89a6f3971f1819fb64bd66717c0c75b0bf63f21ac64a2ebb1a91cd707f8a7a858343cc",
            "copyright": "nicholishen",
            "link": null,
            "version": null
        }
    ]

    To get the optional Excel report the following dependencies must be installed:
    pip install -U pandas openpyxl

Note: Files are only copied. Original files are not moved or deleted. On one hand it is safe to run this script,
but on the other, copied files will consume more disk space.
"""
import contextlib
import datetime as dt
import hashlib
import itertools
import re
import shutil
import typing as typ
from collections import defaultdict
from pathlib import Path

import chardet
import pandas as pd
import openpyxl

try:
    import ujson as json  # ujson is much faster
except ImportError:
    import json

MQL_SRC_FILES = {'.mqh', '.mq4', '.mq5'}
BUFFER_SIZE = 2 ** 16
HASH_ALGO = 'blake2b'
HASH_CLASS = getattr(hashlib, HASH_ALGO)
RE_PATTERNS = {
    'copyright': re.compile(r'^#property\scopyright\s*"(.*?)"\s*$', re.MULTILINE),
    'version'  : re.compile(r'^#property\sversion\s*"(.*?)"\s*$', re.MULTILINE),
    'link'     : re.compile(r'^#property\slink\s*"(.*?)"\s*$', re.MULTILINE),
}


def hash_file(file: Path):
    with contextlib.suppress(PermissionError):
        hasher = HASH_CLASS()
        with file.open('rb') as f:
            while True:
                data = f.read(BUFFER_SIZE)
                if not data:
                    break
                hasher.update(data)
        hashcode = hasher.hexdigest()
        return hashcode
    return None


def last_index_of(iterable, item):
    """Get the last index of item instead of first"""
    index = -1
    for i, thing in enumerate(iterable):
        if thing == item:
            index = i
    return index


def indent_line(text, spaces=4):
    return f"{' ' * spaces}{text}"


def mql_src_details(file: Path, dump_file_text=False):
    try:
        if file.suffix == '.mqproj':
            data = json.loads(file.read_text())
            return {k: data[k] for k in RE_PATTERNS.keys()}
        if file.suffix not in MQL_SRC_FILES:
            raise ValueError
        text = file.read_bytes()
        encoding = chardet.detect(text)['encoding'].lower()
        text = (
            text
                .decode(encoding)
                .encode('utf-8', 'ignore')
                .decode('utf-8', 'ignore')
                # .replace('\r\n', '\n')
        )

        def get(regex):
            try:
                return regex.search(text).group(1)
            except Exception:
                return None

        res = {k: get(regex) for k, regex in RE_PATTERNS.items()}
    except Exception:
        encoding = None
        text = None
        res = {k: None for k in RE_PATTERNS.keys()}
    res['encoding'] = encoding
    if dump_file_text and file.suffix in MQL_SRC_FILES:
        res['file_text'] = text
    return res


def file_report_for_manifest(checksum: str, file_path: Path, dump_file_text=False):
    stat = file_path.stat()
    d = {
        'name'         : file_path.name,
        'extension'    : file_path.suffix,
        'is_src'       : bool(file_path.suffix in MQL_SRC_FILES),
        'file_size'    : stat.st_size,
        'time_modified': str(dt.datetime.fromtimestamp(stat.st_mtime)),
    }
    d.update(mql_src_details(file_path, dump_file_text))
    d.update({
        'path'    : str(file_path.absolute()),
        'checksum': checksum,
    })
    return d


class MqlOrganizer:

    def __init__(self, search_path, save_path, compiled_files=False, **kwargs):
        self.save_path = Path(save_path)
        self.save_path.mkdir(parents=True, exist_ok=True)
        self.search_path = Path(search_path)
        self.report_file_json = self.save_path / 'FILE_REPORT.json'
        self.glob_pattern = '**/*.*'
        self.mql_path_parts = {'MQL4', 'MQL5'}
        self.loose_extensions = MQL_SRC_FILES.copy()
        if compiled_files:
            self.loose_extensions.update({'.ex4', '.ex5'})
        self.bound_extensions = {
            '.dll', '.mqproj', '.py', '.cl', '.tpl', '.html', '.set', '.wav',
            '.chr', '.wnd', '.bin', '.ini', '.bmp', '.png', '.txt', '.csv'
        }
        self.unorganized_dir = self.save_path / kwargs.get('unorganized_dirname', 'UNORGANIZED')
        self.manifest = set()
        self.files_by_checksum = defaultdict(lambda: defaultdict(set))
        self.res_checksum_map = defaultdict(set)
        self.diff_files = set()
        self.git_paths = set()
        self.file_count = len(self.manifest)

    def gather_files(self, verbose=False, is_git=True):
        loose_extensions = self.loose_extensions
        bound_extensions = self.bound_extensions
        counter = 0
        for file in self.search_path.glob(self.glob_pattern):
            path_parts_set = set(file.parts)
            if '$Recycle.Bin' in path_parts_set:
                continue
            is_mql_path = bool(path_parts_set & self.mql_path_parts)
            ext = file.suffix
            if ((ext in loose_extensions) or
                    (is_mql_path and (ext in bound_extensions or (is_git and '.git' in path_parts_set)))
            ):
                checksum = hash_file(file)
                self.files_by_checksum[checksum][is_mql_path].add(file)
                counter += 1
                if verbose and file is not None:
                    print(f"[{counter:05}] {file.name}\n({HASH_ALGO})CHECKSUM = {checksum}")
        return self.files_by_checksum

    def get_new_path(self, file: Path) -> typ.Tuple[bool, Path]:
        parts = set(file.parts)
        mql_path_part = parts & self.mql_path_parts
        if len(mql_path_part) == 1:
            mql_dir = mql_path_part.pop()
            with contextlib.suppress(ValueError):
                index = last_index_of(file.parts, mql_dir)
                path_str = '/'.join(file.parts[index:])
                path = self.save_path / path_str
                return (True, path)
        return (False, self.unorganized_dir / file.name)

    def copy_file(self, file: Path, checksum: str) -> typ.Tuple[bool, Path]:
        is_organized, new_path = self.get_new_path(file)
        new_checksum = checksum
        old_path = file
        counter = itertools.count(1)
        while True:
            if new_path.exists() and ((checksum, new_path,) in self.manifest):
                return (False, new_path,)
            elif new_path.exists():
                old_checksum = hash_file(new_path)
                if new_checksum == old_checksum:
                    return (False, new_path,)
                new_file_name = f'{file.stem}({next(counter)}){file.suffix}'
                new_path = new_path.parent / new_file_name
                self.diff_files.add(new_path)
            else:
                new_path.parent.mkdir(parents=True, exist_ok=True)
                if shutil.copy2(str(old_path.absolute()), str(new_path.absolute())):
                    self._gitcheck(new_path)
                    self.manifest.add((checksum, new_path,))
                    self.res_checksum_map[checksum].add(new_path)
                    self.file_count += 1
                return (True, new_path,)

    def run(self, verbose=False):
        if verbose:
            print('Scanning existing files...')
        for fp in self.save_path.glob('**/*.*'):
            self._gitcheck(fp)
            if fp.is_file() and fp.suffix != '.json':
                checksum = hash_file(fp)
                self.manifest.add((checksum, fp,))
                self.res_checksum_map[checksum].add(fp)
        files = self.gather_files(verbose)
        for hash, d in files.items():
            paths = d[True] or d[False]  # don't copy unorganized file if an organized one exists with same checksum!
            for path in paths:
                with contextlib.suppress(PermissionError):
                    is_copy, new_path = self.copy_file(path, hash)
                    if verbose and new_path is not None:
                        print('' if is_copy else 'Skipping...', new_path)

    def report(self, dump_file_text=False):
        print('Generating report...')
        mr = file_report_for_manifest
        report_dict = {
            'time_completed': str(dt.datetime.now()),
            'total_files'   : len(self.manifest),
            'checksum_algo' : HASH_ALGO,
            'search_path'   : str(self.search_path.absolute()),
            'save_path'     : str(self.save_path.absolute()),
            'extensions'    : sorted(self.loose_extensions ^ self.bound_extensions),
            'git_paths'     : sorted(map(str, self.git_paths)),
            'diff_files'    : sorted(map(str, self.diff_files)),
            'manifest'      : [mr(c, p, dump_file_text) for c, p in self.manifest],
        }
        self.report_file_json.write_text(json.dumps(report_dict, indent=4))
        print('JSON report ready @', self.report_file_json)
        return report_dict

    def _gitcheck(self, fp: Path):
        if '.git' in fp.parts:
            git_path = Path(*fp.parts[:fp.parts.index('.git') + 1])
            self.git_paths.add(git_path)


def _input(msg, default, action=None, feedback=None):
    inp = input(f'{msg} [{default}]: ') or default
    if action is None and default in ['y', 'n']:
        action = lambda inp: inp.lower()[0] == 'y'
    action = action or (lambda x: x)
    res = action(inp)
    if feedback is not None:
        print(feedback(res))
    return res


def main():
    search_path = _input(
        msg='Directory to search files',
        default=list(Path().absolute().parents)[-1],
        action=lambda inp: Path(inp),
        feedback=lambda res: f"Searching for MQL files in {res}..."
    )
    save_path = _input(
        msg='Directory to save files',
        default=Path.home() / 'Desktop/MQL_FILES',
        action=lambda inp: Path(inp),
        feedback=lambda res: f"Saving MQL files in {res}..."
    )
    is_compiled = _input(
        msg='Gather compiled .ex* files? (Y/n)',
        default='n',
        feedback=lambda res: f'Gathering compiled files: {res}'
    )
    is_excel_report = _input(
        msg='Would you like to generate an Excel report? (Y/n)',
        default='n',
        feedback=lambda res: f'Generating Excel report: {res}'
    )
    is_text_dump = _input(
        msg='Would you like to dump the text from the MQL src files into the JSON report?',
        default='n',
        feedback=lambda res: f'Dump source-code: {res}'
    )
    input('Press ENTER to begin > ')
    program = MqlOrganizer(search_path, save_path, compiled_files=is_compiled)
    program.run(verbose=True)
    report = program.report(dump_file_text=is_text_dump)
    if is_excel_report:
        excel_path = program.save_path / 'FILE_REPORT.xlsx'
        df = pd.DataFrame(report['manifest']).drop(['file_text'], axis=1)  # noqa
        df.to_excel(excel_path, index=False)
        print(f'Excel report ready @ {excel_path}')


if __name__ == '__main__':
    main()
