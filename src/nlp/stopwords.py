"""
Question and function words that carry no topic: they are dropped from the full-text (BM25) query. In the AND stage they
made a precise match impossible (every word of the question had to be in one unit), and in the OR stage they matched
thousands of units for nothing. Statute vocabulary ("bo'yicha", "tartibda", "huquqi") is deliberately NOT here: it is
the vocabulary of the norms themselves. Words are compared in the FTS spelling (apostrophes removed).
"""
STOPWORDS = frozenset("""
va yoki ham hamda lekin ammo biroq bu shu u bir ikki men sen biz siz ular mening sizning bizning
qanday qanaqa nima nimalar nega nimaga kim kimga qaysi qaysilar qayer qayerga qayerda qachon qancha necha nechta
uchun bilan kabi ya xuddi agar balki
bor yoq kerak mumkin bolsa bolsam bolgan boladi bolmaydi bormi mumkinmi kerakmi qiladi qilish qilsa qilsam
edi ekan ekanligi emas ekanini
menga mening menda mendan manga bizga bizda sizga sizda
iltimos assalomu alaykum salom rahmat
как что какой какая какие какого чем для или при если ли это этот эта эти его ее их мне меня мой можно нужно ли
где когда кто чтобы также а но и в на по с к о об из за от до не ни же бы
what how the for is are of to in on and or a an do does can i my me be by with at from that this it
""".split())
