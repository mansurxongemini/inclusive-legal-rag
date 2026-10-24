#!/usr/bin/env python3
"""
Builds eval/gold_set.jsonl: 76 questions (26 uz, 25 ru, 25 en) on disability rights.

Every expected unit was read in the live store (data/store) before it was written here. "expected" is a list of slots;
a slot is satisfied when any one of its ids is retrieved (several units of the corpus answer the same point). Types:
short, complex, multi (two or more slots), trap_repealed (the question names a repealed act: the answer must say it
lost force), no_answer (outside the corpus: an honest refusal is the right answer), noisy (typos, mixed languages).
key_facts are regular expressions the answer must contain (numbers and terms of the provision, in any language).

  python eval/build_gold_set.py        # run from the repository root
"""
import json
L = "labor_code_2022_art_"; D = "law_disability_2020_art_"; P = "pension_provision_law_art_"
QUOTA = "o_rq_642_art_39"; INCL = "education_law_2020_art_20"; APPEAL = "vmq_62_2022_a9_p_60"
NOSHOW = "vmq_62_2022_a9_p_59"; HOME = "vmq_62_2022_a9_p_16"; TAX = "tax_code_2020_art_380"
F36 = r"36|o.ttiz olti|тридцат\w* шест|thirty[- ]six"
F30 = r"\b30\b|o.ttiz|тридцат|thirty"
F14 = r"\b14\b|o.n to.rt|четырнадцат|fourteen"
F3 = r"\b3\s*(%|foiz|процент|per ?cent)|uch foiz|тр[её]х процент|three per ?cent"
F20 = r"\b20\b|yigirma|двадцат|twenty"
FONE = r"\b1\b|bitta|kamida bir|одн|\bone\b|at least one"
FAN = r"\b30\b|o.ttiz|тридцат|thirty"
FYEAR = r"har yili|ежегодн|каждый год|annual|every year|yearly"
FDAY = r"bir dam olish|qo.shimcha bir|bir kun|1 kun|один\w* (дополнительн\w* )?выходн|дополнительн\w* выходн|one (additional |extra )?day|additional day"
FBUDGET = r"budjet|бюджет|budget"
FCONSENT = r"rozilig|соглас|consent"
FTHREE = r"\buch\b|\b3\b|тр[иё]|three"
REPEAL = r"kuchini yo.qotgan|o.z kuchini|kuchda emas|утрат|не действ|отмен|repeal|no longer (in force|valid|appl)|lost (its )?(legal )?force|not in force|invalid"

def item(i, lang, qtype, topic, q, slots=(), facts=(), refuse=False, trap=False, note=""):
    return {"id": i, "language": lang, "type": qtype, "topic": topic, "question": q,
            "expected": [list(s) for s in slots], "expect_refusal": refuse,
            "key_facts": list(facts), "trap_repealed": trap, "must_mention_repeal": REPEAL if trap else "",
            "note": note}

uz = [
 item("uz01","uz","short","work_conditions","I guruh nogironligi bo'lgan xodim haftasiga necha soat ishlaydi?",[[L+"427"]],[F36],note="MK 427: haftasiga 36 soatdan oshmaydi"),
 item("uz02","uz","short","work_conditions","II guruh nogironligi bo'lgan xodimga yillik mehnat ta'tili necha kun beriladi?",[[L+"429"]],[F30],note="MK 429: kamida 30 kalendar kun"),
 item("uz03","uz","short","employment_quota","Nogironligi bo'lgan shaxslar uchun ish o'rinlarining eng kam soni tashkilot xodimlarining necha foizidan kam bo'lmasligi kerak?",[[QUOTA]],[F3],note="O'RQ-642 39-modda: nogironligi bo'lgan shaxslar uchun uch foizidan kam emas"),
 item("uz04","uz","short","disability_group","Tibbiy-ijtimoiy ekspert komissiyasi tibbiy hujjatlar qabul qilingandan keyin qancha muddatda tekshiruv o'tkazishi shart?",[[D+"31"]],[F20],note="O'RQ-641 31-modda: 20 kalendar kundan kechiktirmay"),
 item("uz05","uz","short","social_protection","Mehmonxonalar nogironlar aravachasidan foydalanuvchilar uchun nechta xonani moslashtirishi shart?",[[D+"25"]],[FONE],note="O'RQ-641 25-modda: kamida bitta xona"),
 item("uz06","uz","short","social_protection","Nogironligi bo'lgan shaxsning faksimil imzosi nima va undan qachon foydalaniladi?",[[D+"29"]],note="O'RQ-641 29-modda"),
 item("uz07","uz","short","benefits","O'n olti yoshga to'lmagan nogironligi bo'lgan bolani tarbiyalayotgan ota-onaga oyiga qo'shimcha dam olish kuni beriladimi?",[[L+"399"]],[FDAY],note="MK 399: oyiga qo'shimcha bir dam olish kuni"),
 item("uz08","uz","short","work_conditions","Nogironligi bo'lgan xodimlar majburiy tibbiy ko'rikdan qanchalik tez-tez o'tadi va uning xarajatini kim to'laydi?",[[L+"426"]],[FYEAR],note="MK 426: har yili, ish beruvchi hisobidan"),
 item("uz09","uz","short","social_protection","Protez-ortopediya moslamalari bilan ta'minlash xarajatlari qaysi mablag'lar hisobidan qoplanadi?",[[D+"34"]],[FBUDGET],note="O'RQ-641 34-modda: Davlat budjeti mablag'lari"),
 item("uz10","uz","complex","work_conditions","Men II guruh nogironiman. Ish beruvchi meni yillik ta'tilimdan chaqirib olib, dam olish kuni ishlashga majburlamoqchi. U bunga haqlimi?",[[L+"429"],[L+"428"]],[FCONSENT],note="MK 429: chaqirib olish mumkin emas; MK 428: faqat roziligi bilan"),
 item("uz11","uz","complex","disability_group","Tuman TIEK menga nogironlik bermadi, xulosasiga qo'shilmayman. Qayerga va qancha muddatda shikoyat qilsam bo'ladi?",[[APPEAL]],[F30],note="VMQ-62 nizom 60-band: 30 kalendar kun ichida viloyat TIEKga yoki sudga"),
 item("uz12","uz","complex","work_conditions","Ish beruvchi nogironligim borligini bilib, meni ishga olishdan bosh tortdi. Bu qonuniymi?",[[L+"425",L+"4",D+"18"]],note="MK 425: nogironligi sababli mehnat shartnomasi tuzishni rad etish mumkin emas"),
 item("uz13","uz","multi","work_conditions","I guruh nogironligi bo'lgan xodimning qisqartirilgan ish vaqti uchun ish haqi kamayadimi va u yiliga necha kunlik ish haqi saqlanmaydigan ta'til olishi mumkin?",[[L+"431"],[L+"430"]],[F14],note="MK 431: to'liq ish vaqti miqdorida; MK 430: 14 kungacha"),
 item("uz14","uz","multi","pension","Nogironlik pensiyasi kimlarga tayinlanadi va mehnatda mayib bo'lgan shaxsdan ish staji talab qilinadimi?",[[P+"15"],[P+"17"]],note="Pensiya qonuni 15 va 17-moddalar"),
 item("uz15","uz","multi","benefits","Nogironligi bo'lgan bolasi bor ota-ona ishda qanday qo'shimcha ta'til va dam olish kunlariga ega?",[[L+"401",L+"402"],[L+"399"]],note="MK 401 (4 kun haq to'lanadigan), 402 (14 kungacha haqsiz), 399 (oyiga 1 kun)"),
 item("uz16","uz","trap_repealed","benefits","1991-yilgi “O'zbekiston Respublikasida nogironlarni ijtimoiy himoya qilish to'g'risida”gi qonunga ko'ra nogironlarga qanday imtiyozlar beriladi?",[[D+"46"]],trap=True,note="O'RQ-641 46-modda: 422-XII qonun o'z kuchini yo'qotgan"),
 item("uz17","uz","trap_repealed","social_protection","Vazirlar Mahkamasining 2021-yil 29-apreldagi 257-son qaroriga ko'ra Nogironligi bo'lgan shaxslar ishlari bo'yicha idoralararo kengash qanday ishlaydi?",[["vmq_769_2021_p_5"]],trap=True,note="VMQ-769 5-band: 257-son qaror o'z kuchini yo'qotgan"),
 item("uz18","uz","no_answer","out_of_scope","Germaniyada nogironlik pensiyasi qancha miqdorda to'lanadi?",refuse=True,note="Chet el qonunchiligi bazada yo'q"),
 item("uz19","uz","no_answer","out_of_scope","Palov qanday tayyorlanadi?",refuse=True,note="Huquqiy savol emas"),
 item("uz20","uz","noisy","work_conditions","nogronligi bor 2-gurux xodim hafatsiga nechchi soat ishlaydi",[[L+"427"]],[F36],note="Imlo xatolari; MK 427"),
 item("uz21","uz","noisy","work_conditions","II guruh invalid otpusk necha kun beriladi",[[L+"429"]],[F30],note="Aralash til (ruscha so'zlar); MK 429"),
 item("uz22","uz","short","benefits","Bolalikdan nogironligi bo'lgan shaxslar daromad solig'i bo'yicha qanday imtiyozga ega?",[[TAX]],note="Soliq kodeksi 380-modda: jami daromadni kamaytirish"),
 item("uz23","uz","short","disability_group","Nogironlikning nechta guruhi bor va guruhni qaysi organ belgilaydi?",[[P+"16"]],[FTHREE],note="Pensiya qonuni 16-modda: uch guruh, TIEK"),
 item("uz24","uz","short","social_protection","Nogironligi bo'lgan shaxslarga ijtimoiy yordamning qanday turlari ko'rsatiladi?",[[D+"36"]],note="O'RQ-641 36-modda"),
 item("uz26","uz","noisy","social_protection",
      "Ассалаумаликум мен 1 гурух ногироныман хозирда ижарада турипман умрлик юоддашим ишсиз ичтимойи рестрга утмакши "
      "булип ариза ташладим лекин жавоп келмади .Кейнг узлари меники шакирип ташакурнама йоздирип рестрга утасиз деп "
      "ариза калдирдим Лекин еки кунан сунг телефонимга аризан рад этилди деп смс келдим Инсан социал орайига "
      "барганимда улардан мазмунли жавоп алмадим нимага маслахат бера оласиз олдинан рахмат",
      [[f"vmq_35_2026_a4_p_{n}" for n in (6, 7, 27, 33, 42, 45)], [f"vmq_35_2026_a1_p_{n}" for n in (10, 32, 33, 34, 51)]],
      note="Kirill, imlo xatolari, uzun hikoya: ijtimoiy reyestr rad etildi. VMQ-35 4-ilova (apellyatsiya kengashi) va 1-ilova "
           "(rad etish asoslari). Avval tests/test_query_subquestions.py dagi jonli (LIVE_RETRIEVAL_TESTS) test edi."),
 item("uz25","uz","short","education","Nogironligi bo'lgan bolalar maktabgacha ta'limni qayerda oladi va ular uchun qanday sharoit yaratiladi?",[[D+"39"]],note="O'RQ-641 39-modda"),
]
ru = [
 item("ru01","ru","short","work_conditions","Сколько часов в неделю может работать работник с инвалидностью I группы?",[[L+"427"]],[F36],note="ТК 427"),
 item("ru02","ru","short","work_conditions","Какова продолжительность ежегодного трудового отпуска работника с инвалидностью II группы?",[[L+"429"]],[F30],note="ТК 429"),
 item("ru03","ru","short","work_conditions","Может ли работодатель отозвать работника с инвалидностью I группы из ежегодного отпуска?",[[L+"429"]],note="ТК 429: отзыв не допускается"),
 item("ru04","ru","short","work_conditions","Обязан ли работодатель предоставить работнику с инвалидностью II группы отпуск без сохранения заработной платы и какой продолжительности?",[[L+"430"]],[F14],note="ТК 430: до 14 дней"),
 item("ru05","ru","short","employment_quota","Какая минимальная квота рабочих мест для лиц с инвалидностью установлена законом о занятости населения?",[[QUOTA]],[F3],note="Закон о занятости ст. 39"),
 item("ru06","ru","short","disability_group","В какой срок медико-социальная экспертная комиссия должна провести освидетельствование после получения медицинских документов?",[[D+"31"]],[F20],note="Закон 641 ст. 31"),
 item("ru07","ru","short","disability_group","Можно ли пройти медико-социальную экспертизу на дому, если человек по состоянию здоровья не может прийти в комиссию?",[[D+"31",HOME]],note="Закон 641 ст. 31; Положение ВМ-62 п. 16"),
 item("ru08","ru","complex","disability_group","Районная комиссия МСЭ не установила мне инвалидность. Куда и в какой срок можно обжаловать её заключение?",[[APPEAL]],[F30],note="Положение ВМ-62 п. 60: 30 дней"),
 item("ru09","ru","short","pension","Кому назначается пенсия по инвалидности в Узбекистане?",[[P+"15"]],note="Закон о пенсиях ст. 15"),
 item("ru10","ru","short","pension","Нужен ли трудовой стаж для назначения пенсии по инвалидности при трудовом увечье?",[[P+"17"]],note="Закон о пенсиях ст. 17: независимо от стажа"),
 item("ru11","ru","complex","pension","Что будет с пенсией, если человек с инвалидностью без уважительной причины не явился на переосвидетельствование?",[[P+"55",NOSHOW]],note="Закон о пенсиях ст. 55; ВМ-62 п. 59"),
 item("ru12","ru","multi","benefits","Я мать ребёнка с инвалидностью 12 лет. Какие дополнительные отпуска и выходные мне положены на работе?",[[L+"401",L+"402"],[L+"399"]],note="ТК 399, 401, 402"),
 item("ru13","ru","complex","work_conditions","Работодатель хочет отправить меня, работника с инвалидностью, в командировку и на ночную смену без моего согласия. Законно ли это?",[[L+"428"]],[FCONSENT],note="ТК 428: только с согласия"),
 item("ru14","ru","multi","work_conditions","Сколько составляет сокращённое рабочее время работников с инвалидностью I и II группы и уменьшается ли за него зарплата?",[[L+"427"],[L+"431"]],[F36],note="ТК 427, 431"),
 item("ru15","ru","multi","social_protection","Какие обязанности по доступности для людей с инвалидностью есть у гостиниц и у транспортных организаций?",[[D+"25"],[D+"24"]],note="Закон 641 ст. 24, 25"),
 item("ru16","ru","trap_repealed","benefits","Какие льготы инвалидам предусматривает закон «О социальной защищенности инвалидов в Республике Узбекистан» 1991 года?",[[D+"46"]],trap=True,note="Закон 641 ст. 46: закон 422-XII утратил силу"),
 item("ru17","ru","trap_repealed","employment_quota","Что предусматривают пункты 1 и 2 постановления Кабинета Министров № 203 от 20 апреля 2022 года о стимулировании занятости лиц с инвалидностью?",[["vmq_405_2025_p_7"]],trap=True,note="ВМ-405 п. 7: пункты 1 и 2 постановления 203 утратили силу"),
 item("ru18","ru","no_answer","out_of_scope","Какой размер пенсии по инвалидности в Казахстане?",refuse=True,note="Иностранное право"),
 item("ru19","ru","no_answer","out_of_scope","Кто выиграл чемпионат мира по футболу 2022 года?",refuse=True,note="Не юридический вопрос"),
 item("ru20","ru","noisy","work_conditions","инвалид 2 группы отпуск скока дней положено по трудовому кодексу",[[L+"429"]],[F30],note="Разговорный стиль; ТК 429"),
 item("ru21","ru","noisy","work_conditions","nogironligi bor работник 1 группы, сколько часов в неделю рабочее время?",[[L+"427"]],[F36],note="Смешанный язык; ТК 427"),
 item("ru22","ru","short","work_conditions","Кто оплачивает обязательные медицинские осмотры работников с инвалидностью и как часто они проводятся?",[[L+"426"]],[FYEAR],note="ТК 426"),
 item("ru23","ru","short","disability_group","Сколько групп инвалидности существует и кто их устанавливает?",[[P+"16"]],[FTHREE],note="Закон о пенсиях ст. 16"),
 item("ru24","ru","short","social_protection","Какие виды социальной помощи оказываются лицам с инвалидностью?",[[D+"36"]],note="Закон 641 ст. 36"),
 item("ru25","ru","short","education","Как организуется инклюзивное образование для детей с инвалидностью?",[[INCL,D+"38"]],note="Закон об образовании ст. 20; Закон 641 ст. 38"),
]
en = [
 item("en01","en","short","work_conditions","How many hours per week may an employee with a Group I disability work?",[[L+"427"]],[F36],note="Labour Code 427"),
 item("en02","en","short","work_conditions","How long is the annual leave of an employee with a Group II disability?",[[L+"429"]],[F30],note="Labour Code 429"),
 item("en03","en","short","employment_quota","What is the minimum share of jobs that must be reserved for persons with disabilities?",[[QUOTA]],[F3],note="Employment law art. 39"),
 item("en04","en","short","disability_group","Within how many days must the medical and social expert commission examine a person after receiving the medical documents?",[[D+"31"]],[F20],note="Law 641 art. 31"),
 item("en05","en","short","disability_group","Can the disability assessment be carried out at home if the person cannot come to the commission because of their health?",[[D+"31",HOME]],note="Law 641 art. 31; Regulation 62 item 16"),
 item("en06","en","complex","disability_group","The district medical and social expert commission refused to grant me a disability. How can I appeal its decision and what is the deadline?",[[APPEAL]],[F30],note="Regulation 62 item 60: 30 days"),
 item("en07","en","short","social_protection","Who pays for prostheses and orthopedic devices for persons with disabilities?",[[D+"34"]],[FBUDGET],note="Law 641 art. 34"),
 item("en08","en","short","social_protection","What is the facsimile signature of a person with a disability?",[[D+"29"]],note="Law 641 art. 29"),
 item("en09","en","short","social_protection","Do hotels have to provide rooms adapted for wheelchair users?",[[D+"25"]],[FONE],note="Law 641 art. 25"),
 item("en10","en","short","education","Is inclusive education provided for children with disabilities in Uzbekistan?",[[INCL,D+"38"]],note="Education law art. 20; Law 641 art. 38"),
 item("en11","en","short","pension","Who is entitled to a disability pension?",[[P+"15"]],note="Pension law art. 15"),
 item("en12","en","complex","work_conditions","I have a Group II disability and my employer wants me to work night shifts and on weekends. Can they require that?",[[L+"428"]],[FCONSENT],note="Labour Code 428"),
 item("en13","en","complex","work_conditions","My employer refused to hire me because of my disability. Is that allowed?",[[L+"425",L+"4",D+"18"]],note="Labour Code 425"),
 item("en14","en","multi","benefits","What extra leave and days off does a parent of a disabled child under 16 have at work?",[[L+"401",L+"402"],[L+"399"]],note="Labour Code 399, 401, 402"),
 item("en15","en","multi","work_conditions","How short is the working week of employees with a Group I disability, and is their salary reduced for it?",[[L+"427"],[L+"431"]],[F36],note="Labour Code 427, 431"),
 item("en16","en","trap_repealed","benefits","Under the 1991 law 'On social protection of disabled persons in the Republic of Uzbekistan', what benefits do disabled people get?",[[D+"46"]],trap=True,note="Law 641 art. 46: law 422-XII repealed"),
 item("en17","en","trap_repealed","social_protection","How does the interagency council for persons with disabilities work under Cabinet of Ministers Resolution No. 257 of 29 April 2021?",[["vmq_769_2021_p_5"]],trap=True,note="Resolution 769 item 5: Resolution 257 repealed"),
 item("en18","en","no_answer","out_of_scope","What is the disability benefit amount in the United Kingdom?",refuse=True,note="Foreign law"),
 item("en19","en","no_answer","out_of_scope","Give me a recipe for chocolate cake.",refuse=True,note="Not a legal question"),
 item("en20","en","noisy","work_conditions","disabled worker grp 1 how many hours a week uzbekistan labour code??",[[L+"427"]],[F36],note="Informal; Labour Code 427"),
 item("en21","en","noisy","work_conditions","nogironlik group II annual leave how many days?",[[L+"429"]],[F30],note="Mixed language; Labour Code 429"),
 item("en22","en","short","work_conditions","Must employees with disabilities undergo medical examinations every year, and who pays for them?",[[L+"426"]],[FYEAR],note="Labour Code 426"),
 item("en23","en","short","disability_group","How many disability groups are there and which body determines them?",[[P+"16"]],[FTHREE],note="Pension law art. 16"),
 item("en24","en","short","social_protection","What types of social assistance are provided to persons with disabilities?",[[D+"36"]],note="Law 641 art. 36"),
 item("en25","en","short","education","Where do children with disabilities receive preschool education?",[[D+"39"]],note="Law 641 art. 39"),
]
with open("eval/gold_set.jsonl", "w", encoding="utf-8") as f:
    for it in uz + ru + en:
        f.write(json.dumps(it, ensure_ascii=False) + "\n")
print(len(uz), len(ru), len(en))
