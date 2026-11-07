# Canlı koşuda görünür sözleşme ile oracle arayüzü uyumsuzluğu

Bu kayıt uygulayıcının bulgu analizidir; bağımsız denetçi onayı değildir.
Kaynak, `experiments/cli-full-matrix-2026-11-07/candidate.json` içindeki
`fix_even_median`, tekrar 0 satırıdır. Donmuş kaynak sürümü `7e20cdb`.

Koşu iki tur sonunda iç kapılardan `accepted` aldı. Teslim edilen uygulama
tek sayıda eleman için ortadaki tam sayıyı, çift sayıda eleman için
`Fraction(a[middle - 1] + a[middle], 2)` döndürüyor. Dış oracle'ın
`json.dumps(..., allow_nan=False)` işlemi `Fraction` nesnesini kodlayamadı;
`oracle_passed=false`. Kayıt 240.287 token ve 388,689 saniye içerir.
Çağrı bazında USD dökümü yoktur.

Görev metni sonuç türü veya JSON arayüzü belirtmiyor. İlk turdaki modeller
sınırsız tam sayılarda kayan nokta taşmasını ve yuvarlanmasını hata sayıp
ikinci turda tam kesir hesabı istedi. Dolayısıyla bu satır oracle'a göre
yanlış kabuldür; tek başına medyan hesabının matematiksel olarak yanlış
olduğunu kanıtlamaz. Test taşıma biçiminin getirdiği şartın görevden
saklı kalması deneyin bir sözleşme açığıdır.

Eski satırlar, oracle ve görev metni korunur. Başarısız satır sonradan
başarılıya çevrilemez veya matristen çıkarılamaz. Bu kolda sıfır yanlış kabul
şartı artık sağlanamaz. Gelecek deney için ayrı `core-v3` sözleşmesi, JSON
ile taşınan dönüş değerlerini ve bölme/ortalama için standart sonlu Python
kayan nokta semantiğini açıkça belirtmelidir. v2 ile v3 sonuçları aynı
protokol altında birleştirilemez. Yeni sürüm için yeni hazırlık ve yeni
checkpoint dizini gerekir.

`core-v3` uygulandı: tüm görevler dönüş arayüzünü ve standart kayan nokta
semantiğini açıkça taşır; eski metinler ve gizli vakalar korunur. Hazırlık
varsayılanı v3'tür. Gerçek Docker regresyonu üç sayısal görevin referans
çözümlerini kabul ederken Fraction dönüşünü ve eski hatalı medyanı reddetti.
Bu kontrol yeni model çözümünün başarısını veya 5X kazancını kanıtlamaz.
