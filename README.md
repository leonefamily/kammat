# kammat
**MATSim data manipulation tool created at KAM Brno, Czechia**\
![kammat.png](kammat.png)

A module to handle transformation of input data into MATSim format
and process its outputs.

Word _kammat_ means _combed_ in Swedish, hence the choice of the logo design and the purpose overall -
make process of generating MATSim population more straightforward and easy.


## Installation
### Windows

### Linux
_Tested with Ubuntu 22.04.2 (Jammy Jellyfish), Python 3.10_
1. Open repository's root folder in the terminal and run `sudo ./install.sh`.
Bash script creates virtual environment in current directory using your system
main python interpreter, and installs `mmdms` with dependencies in it.
Wait until the process is done. You might need to install `pip3` package using
`sudo apt-get install python3-pip` prior to the rest of installation
2. Once framework is correctly installed, allow executing `run.sh` through
your file manager (in Nautilus right-click the file -> `Properties` -> `Permissions`
-> check `Allow executing file as program` and then double-click the file every time
you need it) or through Terminal using `sudo chmod +x run.sh`.
Script handles framework's GUI startup inside the created virtual environment.
## Usage
### Types of input data
You can find every file's example in `examples` directory.

Main limitations:
- if _non-strict diaries_ are used, _times_ are obligatory;
- if _strict diaries_ are used, _target_probabilities_ are obligatory;
- _more..._