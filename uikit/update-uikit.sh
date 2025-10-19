#!/bin/bash

rm -f uikit*
wget https://raw.githubusercontent.com/uikit/uikit/refs/heads/main/dist/css/uikit.min.css
wget https://raw.githubusercontent.com/uikit/uikit/refs/heads/main/dist/js/uikit.min.js
wget https://raw.githubusercontent.com/uikit/uikit/refs/heads/main/dist/js/uikit-icons.min.js
chmod 644 uikit*

