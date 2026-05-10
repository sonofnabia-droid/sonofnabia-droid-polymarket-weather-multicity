#!/bin/bash

cat << 'EOF' | xargs -I CMD -P 4 bash -c "CMD"
python ankara_download.py --start 2011-01-01
python munich_download.py --start 2008-01-01
python buenos_aires_download.py --start 2012-01-01
EOF

