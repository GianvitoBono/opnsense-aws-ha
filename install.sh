#/bin/sh

# Installing deps

## Checking if pip's already installed, if not we'll install it
python3 -m ensurepip

## Installing python deps
pip install -r requirements.txt

# Coping script to destination folder
mkdir /usr/local/share/ha
cp ha.py /usr/local/share/ha

# Creating RC service to start the script with nohup
cat <<EOF > /usr/local/etc/rc.syshook.d/start/105-ha
#!/bin/sh
cd /usr/local/share/ha ; /usr/bin/nohup /usr/local/bin/python3 ha.py >> /var/log/ha.log 2> /var/log/err.log &
EOF