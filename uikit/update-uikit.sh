#!/bin/bash

rm -f uikit*
wget https://raw.githubusercontent.com/uikit/uikit/refs/heads/main/dist/css/uikit.min.css
wget https://raw.githubusercontent.com/uikit/uikit/refs/heads/main/dist/js/uikit.min.js
wget https://raw.githubusercontent.com/uikit/uikit/refs/heads/main/dist/js/uikit-icons.min.js
cat uikit.min.js uikit-icons.min.js > uikit-all.min.js
chmod 644 uikit*
