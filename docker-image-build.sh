#!/bin/bash
# build image for docker hub

versionFile="VERSION"
if [[ ! -f ${versionFile} ]]; then
    echo "Version file not found!"
    exit 1
fi

version=$(cat ${versionFile})
docker build -t nullata/webui-manager:latest -t nullata/webui-manager:"${version}" .
