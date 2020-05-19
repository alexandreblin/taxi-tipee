#!/bin/sh

release () {
    git checkout master
    echo "__version__ = '$1'" > taxi_tipee/__init__.py
    git commit -m "Bump version number to $1" taxi_tipee/__init__.py
    git tag -m "Release $1" -s $1
    git push origin master $1
    rm dist/*
    ./setup.py sdist
    twine upload dist/*
}

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 VERSION" >&2
    exit 1
fi

while true; do
    read -p "Are you sure you want to release version '$1'? [y/n] " yn
    case $yn in
        [Yy]* ) release $1; break;;
        [Nn]* ) exit;;
        * ) echo "Please answer y or n.";;
    esac
done
