# Maintainer: Jouw Naam <jouwemail@voorbeeld.nl>
pkgname=panostack
pkgver=9.8
pkgrel=1
pkgdesc="Automated high-performance HQ RAW workflow utility for professional photographers"
arch=('any')
license=('GPL3')
depends=('pyside6' 'python-opencv' 'python-numpy' 'darktable' 'hugin' 'enblend-enfuse' 'perl-image-exiftool' 'imagemagick')
# optdepends=('hdrmerge') # Optioneel, handmatig uit AUR

source=('panostack.py')
sha256sums=('SKIP') # Vul hier de SHA256 som in na 'sha256sum panostack.py'

package() {
  install -Dm755 "${srcdir}/panostack.py" "${pkgdir}/usr/bin/panostack"

  # Optioneel: installatie van een desktop entry
  install -d "${pkgdir}/usr/share/applications/"
  echo "[Desktop Entry]
Name=PanoStack
Exec=/usr/bin/panostack
Type=Application
Categories=Graphics;Photography;" > "${pkgdir}/usr/share/applications/panostack.desktop"
}
