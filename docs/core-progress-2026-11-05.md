# İmece çekirdek ilerlemesi — 5 Kasım 2026

P1 kesinti kurtarmasında kalıcı CLI yanıtları gerçek günlük düğümüne,
göreve, tekrara ve donmuş koşu kimliğine bağlanır. Yanıt kaydı diske yazıldıktan
sonra günlük tamamlanamadan kesinti olursa yeniden başlatma, alanları ve
içerik özetlerini doğrulayarak düğümü tamamlar. Çelişkili kayıtlar reddedilir;
sonucu bilinmeyen çağrılar otomatik tekrarlanmaz. Eski kayıtlarda olmayan
düğüm bağları sonradan tahmin edilmez.

P4 kaynak iptali artık yalnızca mevcut becerinin arşivlenmesi değildir.
Kalıcı oracle iptal kaydı, sonraki yükseltmelerde ve canlı beceri yüklemesinde
kontrol edilir. Yayın, iptal ve yükleme aynı yerel katalog kilidini kullanır;
yeniden yürütme sırasında kilit tutulmaz, yayından hemen önce iptal yeniden
kontrol edilir. Önceden yüklenmiş bağlam geri çekilemez. Eski arşivleme
işlemleri için iptal komutunun tekrar uygulanması gerekir.

Bu turda testler ve canlı kıyaslama kullanıcı talimatıyla çalıştırılmadı.
Statik kontrol ve çevrimdışı hazırlık, kesinti/eşzamanlılık davranışının
çalıştırılarak doğrulanması anlamına gelmez. P0–P5 çıkış ölçütleri ve 5X
kazanç henüz sağlanmış kabul edilmiyor. Web değişiklikleri bu kaydın dışında.

P3 devamında, uyarlamalı Python üretimine iki ardışık üretim kapısı reddinde
aynı dosya/kontrol/yürütme sonucu tekrarlandığında durma kuralı eklendi.
Eksik veya altyapı kaynaklı yürütme kanıtı durgunluk sayılmaz. Gerçek tur
sayısı korunur; sonuç reddedilmiş kalır ve neden ile parmak izi rapora yazılır.
Bu sezgisel sonraki olası iyileşmeyi kaçırabilir; maliyet etkisi ölçülmedi.

Karşılaştırma ve devam kaydı doğrulaması, negatif kullanım sayaçlarını,
geçersiz maliyet tahmini bayraklarını ve sonlu 0–1 aralığı dışındaki güven
değerlerini reddeder. Eksik isteğe bağlı alanlar eski raporlarla uyumluluk
için kabul edilmeye devam eder; eksiklikten yeni ölçüm çıkarılmaz.

Çevrimdışı eşleşmiş hazırlık aracı ve iki Codex yapılandırması eklendi.
`docs/experiments/codex-adaptive-pair-2026-11-05/pair.json` kaydında iki
protokol ve uygulama kimliği eşleşiyor; tek ayar farkı
`adaptive_production=false/true`. Her tarafta 50 × 5 koşu planlandı,
gerçekleşen model çağrısı ve tamamlanan koşu sayısı sıfır. Dört turluk ortak
sınır, iki turdan sonra durma davranışını ileride karşılaştırmaya olanak verir.
Hazırlık mevcut bir çıktı dizininin üzerine yazmaz. Bu kayıt macOS ve ortak
model kimliği kullanır; P5 bağımsızlık, Docker ve maliyet kabulünü sağlamaz.

Kanıt önbelleğinde başarı kaydının alan türleri, backend, hata sınıfı ve
istenen kanıt kimliği denetlenir. Eksik veya tutarsız kayıtlar önbellek
isabeti sayılmaz. Bu değişiklikler için Ruff ve diff kontrolleri geçti;
davranış testleri çalıştırılmadı.

P1 devamında modern CLI kayıtlarının sıra, çağrı/düğüm benzersizliği,
görev üyeliği, model yönlendirmesi ve tamamlanma kanıtı doğrulandıktan sonra
uzlaştırılmasına geçildi. Tanımlı eski kimliksiz kayıtlar yalnızca önek
olarak korunur; eksik kimlikler üretilmez. Yeni günlük kuruluşu tek SQLite
işlemine alındı. Mevcut günlüğün koşu kimliği kayıpsa yeni kimlik atanmaz,
açılış reddedilir. Kullanım limitinde kesilen Codex CLI'ın yazdığı kod
yerel inceleme ve statik kontrollerle tamamlandı; başka model kullanılmadı.

Sonraki devamda uygulama içindeki ve plugin-appserver altındaki Codex
kurulumları `0.166.0-alpha.6` bildirdi; ikinci kurulumla çalışma başlatıldı.
Antigravity'nin model listesinde Gemini 3.8 Flash ve GPT-OSS seçenekleri
görüldü. Claude kullanılmadı. CLI sürümü veya model listesi tek başına ayrı
kota ya da kullanılabilir model erişimi garantisi değildir.

Yürütücü ve kapı raporu çıktı kesilmesini artık açıkça taşır. Kesilmiş veya
kesilme bilgisi eksik çıktı, durgunluk kararında eşit sonuç kanıtı sayılmaz.
Benchmark durdurma callback'i çalışan İmece örneğine de iletilir; yalnızca
görevler arasında kontrol edilmesiyle sınırlı kalmaz. Davranış testleri ve
canlı deneyler bu devamda da çalıştırılmadı.

Günlük bütünlüğü ve kalıcı kayıt yazma hataları için çalışmayı durduran ayrı
hata türü eklendi. Ajan havuzu bu hatayı sıradan başarısız yanıt metnine
çeviremez; iptal temizliğinde ortaya çıkan kayıt hatası da korunur. İkili
paralel aşamalar aynı kuralı uygular. CLI yan kayıt yazma hataları ve
günlük düğümü dışındaki gönderim girişimleri bu hata türünü kullanır.

Çevrimdışı inceleme komutu okunamayan veya kimlik kaydı eksik günlükleri
`journal_errors` altında gösterir; tarama eksikse `journal_scan_complete`
false olur. Bu alan tam DAG bütünlüğü doğrulaması değil, dosyaların
okunabilirlik taramasıdır. Devam ön denetimindeki salt okunur SQLite
bağlantıları artık açıkça kapatılır.

Son devamda günlükte tamamlanma, kesinti ve gönderim öncesi ret geçişleri
yalnızca `running` düğümüne uygulanır ve tam bir satırın değiştiği denetlenir.
Eksik veya beklenmedik durumdaki düğüm sessizce başarı sayılmaz. Dış
referans değerlendirmesi, kesilmiş sandbox sonucunu reddeder. P5 kapısı
tahmini maliyetlerle kabul üretmez; doğrulanmış çağrı makbuzları ayrı
eşleştirme akışında kullanılabilir. Ruff ve biçim kontrolleri geçti;
testler ve canlı kıyaslama çalıştırılmadı.
