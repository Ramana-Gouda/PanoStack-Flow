pkgname=panostack
pkgver=3.5.7
pkgrel=1
pkgdesc="Professional Panorama and HDR stacking utility."
arch=('any')
license=('GPL')
# Arch gebruikt meestal de 'python-' prefix voor bibliotheken
depends=('python' 'pyside6' 'python-opencv' 'python-numpy' 'darktable' 'hugin' 'enblend-enfuse' 'perl-image-exiftool' 'imagemagick')
source=('panostack.py' 'oppepper.xmp')

# Dit lost de 'Integriteitscontroles' fout op
sha256sums=('SKIP' 'SKIP')

package() {
  # Maak de mappen aan
  install -d "$pkgdir/usr/share/panostack"
  install -d "$pkgdir/usr/bin"

  # Kopieer het script en de XMP naar de share map
  install -m755 "$srcdir/panostack.py" "$pkgdir/usr/share/panostack/panostack.py"
  install -m644 "$srcdir/oppepper.xmp" "$pkgdir/usr/share/panostack/oppepper.xmp"

  # Maak een symlink in /usr/bin zodat je 'panostack' kunt typen in de terminal
  ln -s /usr/share/panostack/panostack.py "$pkgdir/usr/bin/panostack"
}
