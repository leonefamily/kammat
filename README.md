# kammat
**MATSim data manipulation tool created at KAM Brno, Czechia**\
![kammat.png](kammat.png)

A module to handle transformation of input data into MATSim format
and process its outputs.

Word _kammat_ means _combed_ in Swedish, hence the choice of the logo design,
it also matches the purpose overall - make process of generating MATSim population
and analyzing its outputs more straightforward and easy.

The project is licensed under GPL v2.[^1] 

[^1]: For now, the external package pt2matsim is included as a .jar file
in /src/bin directory, which is licensed under GPL v2 as well. There are plans to reimplement
that functionality in Python within this tool.

> ### **DISCLAIMER!** 
> This software is currently in alpha state with remains of old and/or bad practice code, 
with incomplete or lacking documentation, no tests and no example files. 
Contents can (and will) change significantly at any moment without notice, use with caution.

## Installation
### Windows
Create a virtual environment using command line by typing `python -m venv .`
in a folder of your choice (`cd` there if necessary), then proceed to activate it
`Scripts/activate.bat`. You should see `(venv)` on the left side of new line.
Then, while in the folder with this package source code, type `pip install .`,
which will automatically use `pyproject.toml` file to get and build the package.
In the result you'll be able to launch the graphical user interface
of this package by typing `kammat-gui` while in the virtual environment.
### Linux
Create a virtual environment using command line by typing `python3 -m venv .`
in a folder of your choice (`cd` there if necessary), then proceed to activate it
`source ./venv/bin/activate`. You should see `(venv)` on the left side of new line.
Then, while in the folder with this package source code, type `pip3 install .`,
which will automatically use `pyproject.toml` file to get and build the package.
In the result you'll be able to launch the graphical user interface
of this package by typing `kammat-gui` while in the virtual environment.
## Usage
### Types of input data
TODO: You will eventually find every file's example in `examples` directory.

Main limitations:
- if _non-strict diaries_ are used, _times_ are obligatory;
- if _strict diaries_ are used, _target_probabilities_ are obligatory;
- _more..._