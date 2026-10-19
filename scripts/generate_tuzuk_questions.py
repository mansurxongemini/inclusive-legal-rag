"""Generates a structured bank of targeted niche questions on Uzbekistan disability law for Tuzuk AI research."""
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SOURCES = BASE_DIR / "data" / "sources"
OUT_FILE = SOURCES / "tuzuk_query_bank.json"

CATEGORIES = [
    {
        "category_id": "msek_tiek",
        "category_name": "Tibbiy-ijtimoiy ekspertiza (VTEK/TIEK) va nogironlikni belgilash",
        "templates": [
            "{guruh}-guruh nogironligini muddatidan oldin qayta ko'rikdan o'tkazish tartibi va asoslari qanday?",
            "TIEK komissiyasi xulosasidan norozi bo'lganda qaysi muddatda va qayerga shikoyat qilinadi?",
            "Muddatsiz (umrbod) nogironlik guruhi qaysi kasalliklar va anatomik nuqsonlarda belgilanadi?",
            "Uzoq muddat davolangan xodim necha kun kasallik varaqasida bo'lgandan so'ng TIEK ko'rigiga yuboriladi?",
            "Xorijda olingan jarohat yoki kasallik bo'yicha O'zbekistonda nogironlik qanday rasmiylashtiriladi?",
            "Nogironlikni belgilashda Yakka tartibdagi reabilitatsiya dasturi (IRD) majburiymi?",
            "Bolalikdan nogironlikni 18 yoshga to'lgandan keyin kattalar guruhiga o'tkazish tartibi qanday?",
            "Harakatlanish imkoniyati cheklangan shaxsni TIEK tomonidan uyida yoki statsionarda ko'rikdan o'tkazish qoidalari qanday?",
            "Ruhiy kasalliklar bo'yicha nogironlikni belgilashda sud qarori yoki vasiylik talab qilinadimi?",
            "Onkologik kasallikka chalingan fuqaroga nogironlik guruhi qachon va qanday mezonlar bilan beriladi?",
        ]
    },
    {
        "category_id": "reabilitatsiya_texnika",
        "category_name": "Reabilitatsiya texnik vositalari va protez-ortopediya",
        "templates": [
            "Nogironligi bo'lgan shaxsga elektr yuritgichli aravacha davlat hisobidan qanday tartibda beriladi?",
            "O'z hisobidan sotib olingan protez yoki kreslo-aravacha puli davlat tomonidan qoplanadimi?",
            "Eshitish moslamasi (apparati) va koxlear implant bilan davlat hisobidan ta'minlash shartlari qanday?",
            "Nogironligi bo'lgan shaxsga ajratilgan protez yoki aravachani necha yilda yangisiga almashtirish mumkin?",
            "Ko'zi ojiz shaxslar uchun ovozli tonometr, termometr va Brayl soatlari davlat tomonidan beriladimi?",
            "Bir martalik gigiyena vositalari (pampers/tagliklar) bilan bepul ta'minlash tartibi qanday?",
            "Protez-ortopediya buyumlarini ta'mirlash xarajatlari davlat tomonidan to'lanadimi?",
            "Nogiron bolalar uchun maxsus vertikalizator va yurish moslamalari olish tartibi qanday?",
            "Surdotexnika va tiflotexnika vositalarini olish uchun ariza qaysi organga topshiriladi?",
            "Protez buyumlari olish uchun berilgan sertifikat (vaucher) qancha muddat amal qiladi?",
        ]
    },
    {
        "category_id": "pensiya_va_nafaqa",
        "category_name": "Pensiyalar, nafaqalar va to'lovlar",
        "templates": [
            "Ish stajiga ega bo'lmagan {guruh}-guruh nogironiga qancha miqdorda nafaqa tayinlanadi?",
            "1-guruh nogironligi bo'lgan shaxs bir vaqtning o'zida boquvchisini yo'qotganlik pensiyasini ham olishi mumkinmi?",
            "Nogiron bolani tarbiyalayotgan onalar necha yoshda imtiyozli pensiyaga chiqish huquqiga ega?",
            "Nogironlik pensiyasidan sud qarorisiz yoki aliment uchun qancha qism ushlab qolinishi mumkin?",
            "Nogironligi bo'lgan shaxs ishga kirsa, uning nogironlik pensiyasi to'xtatiladimi yoki to'liq to'lanadimi?",
            "18 yoshdan katta bolalikdan nogiron shaxs vafot etsa, dafn marosimi uchun qancha nafaqa to'lanadi?",
            "Harbiy xizmat majburiyatini bajarishda nogiron bo'lgan shaxslarga pensiya qanday ustama bilan to'lanadi?",
            "Чернобил AES halokatida nogiron bo'lgan fuqarolarga qanday qo'shimcha kompensatsiyalar bor?",
            "Nogironlik pensiyasini tayinlash muddati o'tib ketgan bo'lsa, o'tgan davr uchun pul undirib olinadimi?",
            "1-guruh nogironiga qarayotgan shaxsga parvarishlash nafaqasi qancha miqdorda to'lanadi?",
        ]
    },
    {
        "category_id": "mehnat_munosabatlari",
        "category_name": "Mehnat kafolatlari va ish o'rinlari",
        "templates": [
            "1 va 2-guruh nogironligi bo'lgan xodimlarga haftalik qisqartirilgan ish vaqti necha soat qilib belgilanadi?",
            "Nogironligi bo'lgan xodimga yillik asosiy uzaytirilgan mehnat ta'tili necha kalendar kun berilishi shart?",
            "Nogiron xodim o'z hisobidan (ish haqi saqlanmagan holda) yiliga necha kun ta'til olishga haqli?",
            "Tashkilotda nogironligi bo'lgan shaxslar uchun 3 foizlik ish o'rni kvotasi qanday korxonalarga tatbiq etiladi?",
            "Nogironligi bo'lgan shaxsni ishga qabul qilishda sinov muddati belgilash mumkinmi?",
            "Xodim ish paytida mayib bo'lib nogiron bo'lib qolsa, ish beruvchi qanday tovon puli to'lashi shart?",
            "Nogiron xodimni uning roziligisiz tungi yoki dam olish kunlaridagi ishlarga jalb qilsa bo'ladimi?",
            "Shtatlar qisqarganda nogironligi bo'lgan xodim ishda qolishda imtiyozga egami?",
            "Ko'zi ojiz xodimning ish joyini tiflotexnika bilan jihozlash uchun ish beruvchiga subsidiya beriladimi?",
            "Nogiron xodimni ish beruvchi tashabbusi bilan ishdan bo'shatishda kasaba uyushmasi roziligi shartmi?",
        ]
    },
    {
        "category_id": "soliq_va_bojxona",
        "category_name": "Soliq, boj va davlat bojlari imtiyozlari",
        "templates": [
            "Bolalikdan nogironligi bo'lgan shaxslarning daromad solig'i bo'yicha qanday imtiyozi bor?",
            "1 va 2-guruh nogironlari mol-mulk solig'ini to'lashdan to'liq ozod qilinadimi?",
            "Nogironligi bo'lgan shaxs yer solig'i to'lashdan qaysi maydon doirasida ozod qilinadi?",
            "Nogironligi bo'lgan shaxs sudga da'vo arizasi berganda davlat bojidan qaysi hollarda ozod bo'ladi?",
            "Notarius orqali vasiyatnoma yoki ishonchnoma tasdiqlatishda nogironlarga qanday chegirma bor?",
            "Chet eldan o'zi uchun maxsus moslashtirilgan avtomobil olib kirayotgan nogiron bojxona to'lovlaridan ozodmi?",
            "Nogironlar jamoat birlashmalari tomonidan ishlab chiqarilgan tovarlar QQSdan ozod qilinadimi?",
            "Nogironligi bo'lgan yakka tartibdagi tadbirkor (YaTT) qat'iy belgilangan soliqdan qanday imtiyozga ega?",
            "O'zini o'zi band qilgan nogiron fuqaro daromad solig'i va ijtimoiy soliq to'laydimi?",
            "Davlat xizmatlari markazlarida pasport yoki guvohnoma olishda nogironlarga davlat boji imtiyozi bormi?",
        ]
    },
    {
        "category_id": "talim_va_inklyuziv",
        "category_name": "Ta'lim, OTM kvotasi va inklyuzivlik",
        "templates": [
            "1 va 2-guruh nogironligi bo'lgan abituriyentlar uchun OTMlarga 2 foizlik davlat granti kvotasi tartibi qanday?",
            "Ko'zi ojiz talabalarga darsliklar va o'quv materiallari tayyorlash uchun alohida kotib beriladimi?",
            "Nogiron bolalarni davlat bog'chalarida (MTT) bepul ovqatlantirish tartibi qanday?",
            "Umumta'lim maktablarida inklyuziv sinflar ochish uchun o'quvchilar soni minimal qancha bo'lishi kerak?",
            "Inklyuziv sinfda dars beradigan o'qituvchilarning oylik maoshiga qanday ustama to'lanadi?",
            "Nogironligi bo'lgan talaba OTM yotoqxonasiga navbatsiz va bepul joylashish huquqiga egami?",
            "Magistratura bosqichiga kirishda nogironligi bo'lgan shaxslar uchun qanday imtiyozlar nazarda tutilgan?",
            "Xususiy maktablar inklyuziv ta'limga muhtoj bolalarni qabul qilishdan bosh tortishi qonuniymi?",
            "Alohida ta'lim ehtiyoji bo'lgan bolani uyda yakka tartibda o'qitishda o'qituvchi soatlari qanday to'lanadi?",
            "Imtiyozli qabul qilingan nogiron talaba o'qishini boshqa viloyatga ko'chirishda (perevod) imtiyoz bormi?",
        ]
    },
    {
        "category_id": "uy_joy_kommunal",
        "category_name": "Uy-joy, kommunal to'lovlar va shaharsozlik",
        "templates": [
            "Uy-joyga muhtoj 1 va 2-guruh nogironlariga arzon va bepul uy-joy ajratish tartibi qanday?",
            "Nogironligi bo'lgan shaxslarga kommunal to'lovlar (gaz, svet, suv) uchun oylik kompensatsiya qancha?",
            "Yangi qurilayotgan ko'p qavatli uylarda pandus va ko'targich bo'lmasa, uni qabul qilish qonuniymi?",
            "Uy-joy sotib olish uchun subsidiya olishda nogironligi bo'lgan fuqarolarga qanday ustunlik beriladi?",
            "Og'ir kasallikka chalingan nogiron shaxsga alohida qo'shimcha xona berilishi qaysi me'yorda belgilangan?",
            "Yerto'la yoki 1-qavatda yashovchi nogiron o'z hisobidan shaxsiy pandus o'rnatishi uchun ruxsat kerakmi?",
            "Eski ko'p qavatli uylarning kirish qismiga pandus o'rnatish kimning (boshqaruvchi tashkilot yoki hokimlik) zimmasida?",
            "Nogironligi bo'lgan shaxsga ijara to'lovining bir qismini davlat tomonidan qoplash tartibi bormi?",
            "Ijtimoiy uy-joylarda yashayotgan nogironligi bo'lgan shaxs vafot etsa, uy uning oilasida qoladimi?",
            "Nogironligi bo'lgan shaxslar yashaydigan xonadonlar kommunal qarzdorlik sababli tarmoqdan uzilishi mumkinmi?",
        ]
    },
    {
        "category_id": "tibbiyot_va_dorilar",
        "category_name": "Tibbiy yordam, bepul dorilar va sanatoriylar",
        "templates": [
            "Imtiyozli toifadagi nogironlarga bepul dori vositalari yozib beriladigan retsept shakli qanday?",
            "Nogironligi bo'lgan shaxs respublika ixtisoslashtirilgan tibbiyot markazlariga bepul davolanish orderini qanday oladi?",
            "Sanatoriy-kurortlarda bepul davolanish yo'llanmasi necha yilda bir marta beriladi va navbat qanday tekshiriladi?",
            "Nogiron bolaga qarovchi ota-onaga ham sanatoriyga birga borish uchun yo'llanma beriladimi?",
            "Kam uchraydigan (orfan) kasalliklar ro'yxatiga kirgan bemorlar dori vositalarini qayerdan oladi?",
            "Statsionar shifoxonada davolanayotgan 1-guruh nogironiga bepul ovqat va dori-darmon ta'minoti qanday?",
            "Yurak yoki buyrak operatsiyasiga muhtoj nogiron fuqaroning xarajati qaysi jamg'arma hisobidan to'lanadi?",
            "Nogironligi bo'lgan shaxsga dori vositalari o'rniga naqd pul shaklida kompensatsiya olish mumkinmi?",
            "Chet elda davolanishga muhtoj og'ir nogiron bemorlarga davlat yordami ajratiladimi?",
            "Nogironligi bo'lgan shaxslarni profilaktik dispanser ko'rigidan o'tkazish qanchalik tez-tez o'tkaziladi?",
        ]
    },
    {
        "category_id": "transport_harakat",
        "category_name": "Transport, yo'l harakati va to'xtash joylari",
        "templates": [
            "Shahar yo'lovchi transportida (avtobus, metro) 1 va 2-guruh nogironlari bepul yurish huquqiga egami?",
            "Temir yo'l va samolyot chiptalariga nogironlar uchun yillik 50 foizlik chegirma qanday olinadi?",
            "Avtomobillar to'xtash joylarida nogironlar uchun kamida 10 foiz joy ajratilmagan bo'lsa, kim jarimaga tortiladi?",
            "Avtomobilida 'Nogiron' belgisi bo'lgan haydovchi qaysi yo'l harakati belgilariga bo'ysunmaslik huquqiga ega?",
            "Nogironligi bo'lgan shaxsning shaxsiy avtomobili uchun benzin yoki yoqilg'i kompensatsiyasi qancha to'lanadi?",
            "Taksi xizmatlarida (inklyuziv taksi) nogironligi bo'lgan shaxslarga davlat tomonidan subsidiya beriladimi?",
            "Kreslo-aravachani poyezd yoki samolyotda bepul yuk sifatida tashish me'yorlari qanday?",
            "Jamoat transportida pandus yoki ko'targich ishlamasa, yo'lovchi qayerga shikoyat qilishi mumkin?",
            "Maxsus qo'l boshqaruvli avtomobil sotib olishda bojxona va utilizatsiya yig'imi undiriladimi?",
            "Piyodalar o'tish joyida oq hassa bilan harakatlanayotgan ko'zi ojiz piyodaga haydovchi qanday yo'l berishi shart?",
        ]
    },
    {
        "category_id": "vasiylik_ijtimoiy_xizmat",
        "category_name": "Vasiylik, 'Inson' markazlari va qarovchilik",
        "templates": [
            "1-guruh nogironiga qarab turgan shaxsning qarovchilik davri uning pensiya stajiga qanday qo'shiladi?",
            "'Inson' ijtimoiy xizmatlar markazlari orqali yolg'iz yashovchi nogironga ijtimoiy xodim qanday biriktiriladi?",
            "Ijtimoiy himoya yagona reyestri orqali kam ta'minlanganlik nafaqasi olishda nogironlik nafaqasi daromadga qo'shiladimi?",
            "Muomalaga layoqatsiz deb topilgan nogiron shaxs nomidan mulkni sotish yoki hadya qilish qoidalari qanday?",
            "Nogiron farzandi bor yolg'iz onalarga davlat tomonidan qanday moddiy va ijtimoiy yordamlar beriladi?",
            "Vasiylik va homiylik organining ruxsatisiz nogironning pensiyasini vasiy o'z ehtiyoji uchun sarflashi javobgarlikka sabab bo'ladimi?",
            "Nogiron shaxsga o'zgalar parvarishi zarurligini tasdiqlovchi dalolatnoma qanday tuziladi?",
            "Keksa va nogironlar pansionatiga ('Sahovat' va 'Muruvvat' uylariga) joylashtirish tartibi qanday?",
            "Nogironligi bo'lgan shaxsga bepul yuridik yordam ko'rsatuvchi davlat advokati qanday tayinlanadi?",
            "Nogiron shaxsning shaxsiy ma'lumotlari (tashxisi va guruhi) uning roziligisiz tarqatilsa, qanday jazo bor?",
        ]
    }
]

def main():
    SOURCES.mkdir(parents=True, exist_ok=True)
    all_questions = []
    qid = 1
    
    # We expand templates across multiple groups (1-guruh, 2-guruh, 3-guruh, bolalikdan nogiron)
    group_variants = ["1", "2", "3"]
    
    for cat in CATEGORIES:
        cid = cat["category_id"]
        cname = cat["category_name"]
        for tmpl in cat["templates"]:
            if "{guruh}" in tmpl:
                for g in group_variants:
                    q_text = tmpl.format(guruh=g)
                    all_questions.append({
                        "id": qid,
                        "category_id": cid,
                        "category_name": cname,
                        "question": q_text,
                        "status": "pending"
                    })
                    qid += 1
            else:
                all_questions.append({
                    "id": qid,
                    "category_id": cid,
                    "category_name": cname,
                    "question": tmpl,
                    "status": "pending"
                })
                qid += 1

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_questions, f, ensure_ascii=False, indent=2)

    print(f"Generated {len(all_questions)} structured legal research questions in {OUT_FILE}")

if __name__ == "__main__":
    main()
