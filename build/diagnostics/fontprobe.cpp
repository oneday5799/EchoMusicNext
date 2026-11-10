// Offscreen font database probe: which families registered, and can a Han
// string resolve to real glyphs through the app's uiFont chain?
#include <QGuiApplication>
#include <QFontDatabase>
#include <QFontInfo>
#include <QRawFont>
#include <QImage>
#include <QPainter>
#include <QColor>
#include <cstdio>

int main(int argc, char **argv)
{
    QGuiApplication app(argc, argv);
    const auto fams = QFontDatabase::families();
    printf("families=%d\n", int(fams.size()));
    for (const auto &f : fams)
        printf("  [%s]\n", qPrintable(f));

    QFont f = QFontDatabase::systemFont(QFontDatabase::GeneralFont);
    f.setPixelSize(13);
    f.setStyleHint(QFont::SansSerif);
    QFontInfo info(f);
    printf("default resolved family=[%s] pointSizeF=%f\n", qPrintable(info.family()),
           info.pointSizeF());

    const auto han = QStringLiteral("暂无该音质");
    QRawFont raw = QRawFont::fromFont(f, QFontDatabase::WritingSystem::SimplifiedChinese);
    printf("han raw font family=[%s] valid=%d\n", qPrintable(raw.familyName()), int(raw.isValid()));
    const auto glyphs = raw.glyphIndexesForString(han);
    printf("glyphIndexes:");
    for (quint32 g : glyphs)
        printf(" %u", g);
    printf("\n");

    // Also probe the exact fractional path used by styledUiFont at 1.25 zoom.
    QFont f2 = f;
    f2.setPixelSize(100);
    const auto pointsPerPixel = QFontInfo(f2).pointSizeF() / 100;
    printf("probe pointsPerPixel=%f\n", pointsPerPixel);
    if (pointsPerPixel > 0) {
        f2.setPointSizeF(13.75 * pointsPerPixel);
        QFontInfo info2(f2);
        printf("1.25 resolved family=[%s] pixelSize=%f\n", qPrintable(info2.family()),
               info2.pixelSize());
    }

    QImage img(120, 20, QImage::Format_RGB32);
    img.fill(0xff202020);
    QPainter p(&img);
    p.setFont(f);
    p.setPen(QColor(255, 255, 255));
    p.drawText(img.rect(), Qt::AlignLeft | Qt::AlignVCenter, han);
    p.end();
    int inked = 0;
    for (int y = 0; y < 20; ++y)
        for (int x = 0; x < 120; ++x) {
            const auto c = img.pixelColor(x, y);
            if (qAbs(c.red() - 32) > 25)
                ++inked;
        }
    printf("inked=%d\n", inked);
    img.save(QStringLiteral("D:/Code/EchoMusicNext/build/diagnostics/fontprobe-han.png"));
    return 0;
}
