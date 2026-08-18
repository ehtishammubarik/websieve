#!/bin/bash
pip3 install scrapyd        # To install scrapyd via pip packages
scrapyd > /dev/null 2>&1 &  # To run the scrapyd in background and redirect the logs to dev/null
scrapyd-deploy              # For deploying scrapyd
tail -f /dev/null                       
