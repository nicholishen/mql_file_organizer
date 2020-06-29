# mql_file_organizer
A script that gathers all your MQL files and organizes them together and provides detailed reports in JSON and Excel.

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