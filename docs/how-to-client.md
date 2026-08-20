Set /etc/apt/sources.list.d/official-package-repositories.list
apt update
apt upgrade -y

apt install -y openjdk-17-jdk

wget https://download.racket-lang.org/installers/8.18/racket-8.18-x86_64-linux-buster-cs.sh
sh racket-8.18-x86_64-linux-buster-cs.sh --unix-style --create-dir --dest /usr/
rm racket-8.18-x86_64-linux-buster-cs.sh

wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
apt install -y ./google-chrome-stable_current_amd64.deb
rm google-chrome-stable_current_amd64.deb

apt update
apt install -y software-properties-common apt-transport-https wget gpg
wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > microsoft.gpg
sudo install -D -o root -g root -m 644 microsoft.gpg /usr/share/keyrings/microsoft.gpg
rm -f microsoft.gpg

Set /etc/apt/sources.list.d/vscode.sources to

Types: deb
URIs: https://packages.microsoft.com/repos/code
Suites: stable
Components: main
Architectures: amd64,arm64,armhf
Signed-By: /usr/share/keyrings/microsoft.gpg

sudo apt update
sudo apt install -y code

curl -s https://s3.eu-central-1.amazonaws.com/jetbrains-ppa/0xA6E8698A.pub.asc | gpg --dearmor | sudo tee /usr/share/keyrings/jetbrains-ppa-archive-keyring.gpg > /dev/null
echo "deb [signed-by=/usr/share/keyrings/jetbrains-ppa-archive-keyring.gpg] http://jetbrains-ppa.s3-website.eu-central-1.amazonaws.com any main" | sudo tee /etc/apt/sources.list.d/jetbrains-ppa.list > /dev/null
apt-get update
apt install intellij-idea-community
apt install pycharm-community
