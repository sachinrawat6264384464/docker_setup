"""
Management command to seed India address master data.
Usage: python manage.py seed_india_address
       python manage.py seed_india_address --clear   (clears existing data first)
"""
import time
from django.core.management.base import BaseCommand
from django.db import transaction

# ============================================================
# INDIA MASTER DATA
# Hierarchy: Country → State → District → City → Pincode → Area
# ============================================================

INDIA_DATA = {
    "Andhra Pradesh": {
        "code": "AP",
        "districts": {
            "Anantapur": ["Anantapur", "Dharmavaram", "Guntakal", "Hindupur", "Kadiri", "Tadipatri"],
            "Chittoor": ["Chittoor", "Tirupati", "Madanapalle", "Srikalahasti", "Puttur"],
            "East Godavari": ["Kakinada", "Rajahmundry", "Amalapuram", "Ramachandrapuram", "Samalkot"],
            "Guntur": ["Guntur", "Narasaraopet", "Tenali", "Bapatla", "Mangalagiri", "Tadepalligudem"],
            "Krishna": ["Vijayawada", "Machilipatnam", "Gudivada", "Nuzvid", "Nandigama"],
            "Kurnool": ["Kurnool", "Nandyal", "Adoni", "Yemmiganur", "Pattikonda"],
            "Nellore": ["Nellore", "Kavali", "Gudur", "Atmakur", "Sullurpeta"],
            "Prakasam": ["Ongole", "Markapur", "Chirala", "Kandukur", "Addanki"],
            "Srikakulam": ["Srikakulam", "Narasannapeta", "Palasa", "Rajam", "Tekkali"],
            "Visakhapatnam": ["Visakhapatnam", "Bheemunipatnam", "Anakapalle", "Gajuwaka"],
            "Vizianagaram": ["Vizianagaram", "Bobbili", "Parvathipuram", "Salur"],
            "West Godavari": ["Eluru", "Bhimavaram", "Tadepalligudem", "Palacole", "Narsapur"],
            "YSR Kadapa": ["Kadapa", "Proddatur", "Rajampet", "Jammalamadugu", "Mydukur"],
        }
    },
    "Arunachal Pradesh": {
        "code": "AR",
        "districts": {
            "Itanagar Capital Region": ["Itanagar", "Naharlagun", "Nirjuli"],
            "Lohit": ["Tezu", "Namsai"],
            "Tawang": ["Tawang", "Lumla"],
            "West Siang": ["Aalo (Along)"],
        }
    },
    "Assam": {
        "code": "AS",
        "districts": {
            "Baksa": ["Mushalpur", "Tamulpur"],
            "Barpeta": ["Barpeta", "Barpeta Road", "Sorbhog"],
            "Biswanath": ["Biswanath Chariali", "Gohpur"],
            "Bongaigaon": ["Bongaigaon", "Bijni"],
            "Cachar": ["Silchar", "Sonai", "Lakhipur"],
            "Charaideo": ["Sonari", "Amguri"],
            "Chirang": ["Kajalgaon", "Sidli"],
            "Darrang": ["Mangaldoi", "Kalaigaon"],
            "Dhemaji": ["Dhemaji", "Jonai", "Silapathar"],
            "Dhubri": ["Dhubri", "Gauripur", "Bilasipara"],
            "Dibrugarh": ["Dibrugarh", "Naharkatia", "Moran", "Tinsukia"],
            "Dima Hasao": ["Haflong"],
            "Goalpara": ["Goalpara", "Dudhnoi"],
            "Golaghat": ["Golaghat", "Sarupathar", "Bokakhat"],
            "Hailakandi": ["Hailakandi", "Lala", "Katlicherra"],
            "Hojai": ["Hojai", "Lumding"],
            "Jorhat": ["Jorhat", "Mariani", "Titabar"],
            "Kamrup": ["Guwahati", "Boko", "Palashbari"],
            "Kamrup Metropolitan": ["Guwahati City", "Dispur", "Jalukbari", "Kahilipara"],
            "Karbi Anglong": ["Diphu", "Bokajan", "Hamren"],
            "Karimganj": ["Karimganj", "Badarpur", "Nilambazar"],
            "Kokrajhar": ["Kokrajhar", "Gossaigaon", "Dotma"],
            "Lakhimpur": ["North Lakhimpur", "Dhakuakhana", "Narayanpur"],
            "Majuli": ["Garamur"],
            "Morigaon": ["Morigaon", "Bhurbandha", "Laharighat"],
            "Nagaon": ["Nagaon", "Hojai", "Dhing", "Lanka"],
            "Nalbari": ["Nalbari", "Tihu"],
            "Sivasagar": ["Sivasagar", "Nazira", "Gaurisagar"],
            "Sonitpur": ["Tezpur", "Dhekiajuli", "Rangapara"],
            "South Salmara-Mankachar": ["Hatsingimari"],
            "Tinsukia": ["Tinsukia", "Digboi", "Doom Dooma", "Margherita"],
            "Udalguri": ["Udalguri", "Mangaldai", "Bhergaon"],
            "West Karbi Anglong": ["Baithalangso", "Rongram"],
        }
    },
    "Bihar": {
        "code": "BR",
        "districts": {
            "Araria": ["Araria", "Forbesganj"],
            "Arwal": ["Arwal"],
            "Aurangabad": ["Aurangabad", "Obra", "Daudnagar"],
            "Banka": ["Banka", "Amarpur"],
            "Begusarai": ["Begusarai", "Teghra", "Barauni"],
            "Bhagalpur": ["Bhagalpur", "Naugachia", "Kahalgaon"],
            "Bhojpur": ["Arrah", "Jagdishpur", "Piro"],
            "Buxar": ["Buxar", "Dumraon"],
            "Darbhanga": ["Darbhanga", "Benipur", "Hayaghat"],
            "East Champaran": ["Motihari", "Raxaul", "Bettiah"],
            "Gaya": ["Gaya", "Bodh Gaya", "Tekari", "Nagar Nausa"],
            "Gopalganj": ["Gopalganj", "Hathua"],
            "Jamui": ["Jamui", "Jhajha"],
            "Jehanabad": ["Jehanabad"],
            "Kaimur": ["Bhabua", "Mohania"],
            "Katihar": ["Katihar", "Manihari", "Barari"],
            "Khagaria": ["Khagaria", "Mansi"],
            "Kishanganj": ["Kishanganj", "Bahadurganj"],
            "Lakhisarai": ["Lakhisarai", "Suryagarha"],
            "Madhepura": ["Madhepura", "Udakishanganj"],
            "Madhubani": ["Madhubani", "Jaynagar", "Jhanjharpur"],
            "Munger": ["Munger", "Jamalpur"],
            "Muzaffarpur": ["Muzaffarpur", "Kanti", "Sitamarhi"],
            "Nalanda": ["Bihar Sharif", "Rajgir", "Hilsa"],
            "Nawada": ["Nawada", "Rajauli"],
            "Patna": ["Patna", "Danapur", "Patna Sahib", "Phulwari Sharif", "Khagaul"],
            "Purnia": ["Purnia", "Kasba", "Bhawanipur"],
            "Rohtas": ["Sasaram", "Bikramganj", "Dehri"],
            "Saharsa": ["Saharsa", "Simri Bakhtiyarpur"],
            "Samastipur": ["Samastipur", "Dalsinghsarai", "Rosera"],
            "Saran": ["Chapra", "Sonpur", "Revelganj"],
            "Sheikhpura": ["Sheikhpura", "Barbigha"],
            "Sheohar": ["Sheohar", "Piprahi"],
            "Sitamarhi": ["Sitamarhi", "Dumra", "Pupri"],
            "Siwan": ["Siwan", "Mairwa", "Hussainganj"],
            "Supaul": ["Supaul", "Triveniganj"],
            "Vaishali": ["Hajipur", "Mahua", "Lalganj"],
            "West Champaran": ["Bettiah", "Bagaha", "Narkatiaganj"],
        }
    },
    "Chhattisgarh": {
        "code": "CG",
        "districts": {
            "Balod": ["Balod", "Gunderdehi"],
            "Baloda Bazar": ["Baloda Bazar", "Bhatapara"],
            "Balrampur": ["Balrampur", "Ramanujganj"],
            "Bastar": ["Jagdalpur", "Tokapal"],
            "Bemetara": ["Bemetara", "Berla"],
            "Bijapur": ["Bijapur", "Bhopalpatnam"],
            "Bilaspur": ["Bilaspur", "Ratanpur", "Masturi"],
            "Dantewada": ["Dantewada", "Geedam"],
            "Dhamtari": ["Dhamtari", "Kurud"],
            "Durg": ["Durg", "Bhilai", "Patan"],
            "Gariaband": ["Gariaband", "Mainpur"],
            "Gaurela-Pendra-Marwahi": ["Gaurela", "Pendra", "Marwahi"],
            "Janjgir-Champa": ["Janjgir", "Sakti", "Champa"],
            "Jashpur": ["Jashpur Nagar", "Kunkuri"],
            "Kabirdham": ["Kawardha", "Pandariya"],
            "Kanker": ["Kanker", "Bhanupratappur"],
            "Kondagaon": ["Kondagaon", "Keshkal"],
            "Korba": ["Korba", "Katghora"],
            "Koriya": ["Baikunthpur", "Manendragarh"],
            "Mahasamund": ["Mahasamund", "Basna"],
            "Mungeli": ["Mungeli", "Lormi"],
            "Narayanpur": ["Narayanpur", "Orchha"],
            "Raigarh": ["Raigarh", "Sarangarh", "Gharghoda"],
            "Raipur": ["Raipur", "Arang", "Tilda", "Abhanpur"],
            "Rajnandgaon": ["Rajnandgaon", "Dongargarh", "Khairagarh"],
            "Sukma": ["Sukma", "Konta"],
            "Surajpur": ["Surajpur", "Premnagar"],
            "Surguja": ["Ambikapur", "Sitapur"],
        }
    },
    "Goa": {
        "code": "GA",
        "districts": {
            "North Goa": ["Panaji", "Mapusa", "Calangute", "Candolim", "Porvorim", "Vasco da Gama"],
            "South Goa": ["Margao", "Ponda", "Vasco", "Curchorem", "Quepem"],
        }
    },
    "Gujarat": {
        "code": "GJ",
        "districts": {
            "Ahmedabad": ["Ahmedabad", "Gandhinagar", "Naroda", "Odhav", "Vatva", "Bopal", "Satellite", "Maninagar"],
            "Amreli": ["Amreli", "Rajula", "Savarkundla"],
            "Anand": ["Anand", "Vallabh Vidyanagar", "Borsad", "Petlad"],
            "Aravalli": ["Modasa", "Bhiloda"],
            "Banaskantha": ["Palanpur", "Deesa", "Dhanera"],
            "Bharuch": ["Bharuch", "Ankleshwar", "Jhagadia"],
            "Bhavnagar": ["Bhavnagar", "Mahuva", "Palitana", "Sihor"],
            "Botad": ["Botad", "Gadhada"],
            "Chhota Udaipur": ["Chhota Udaipur", "Kawant"],
            "Dahod": ["Dahod", "Limkheda"],
            "Dang": ["Ahwa"],
            "Devbhoomi Dwarka": ["Dwarka", "Khambhalia", "Okha"],
            "Gandhinagar": ["Gandhinagar", "Mansa", "Kalol"],
            "Gir Somnath": ["Veraval", "Somnath", "Una", "Kodinar"],
            "Jamnagar": ["Jamnagar", "Kalavad", "Dhrol"],
            "Junagadh": ["Junagadh", "Keshod", "Mangrol", "Porbandar"],
            "Kheda": ["Nadiad", "Anand", "Kapadvanj", "Matar"],
            "Kutch": ["Bhuj", "Anjar", "Gandhidham", "Mandvi", "Mundra", "Adipur"],
            "Mahisagar": ["Lunawada", "Balasinor"],
            "Mehsana": ["Mehsana", "Unjha", "Visnagar", "Kadi", "Patan"],
            "Morbi": ["Morbi", "Wankaner", "Wadhwan"],
            "Narmada": ["Rajpipla", "Dediapada"],
            "Navsari": ["Navsari", "Chikhli", "Bilimora"],
            "Panchmahal": ["Godhra", "Halol", "Kalol", "Lunavada"],
            "Patan": ["Patan", "Harij", "Sidhpur"],
            "Porbandar": ["Porbandar", "Ranavav"],
            "Rajkot": ["Rajkot", "Gondal", "Jetpur", "Morbi", "Wankaner"],
            "Sabarkantha": ["Himmatnagar", "Idar", "Talod"],
            "Surat": ["Surat", "Navsari", "Bardoli", "Mandvi", "Kamrej", "Olpad"],
            "Surendranagar": ["Surendranagar", "Wadhwan", "Dhrangadhra", "Halvad"],
            "Tapi": ["Vyara", "Songadh"],
            "Vadodara": ["Vadodara", "Anand", "Padra", "Karjan", "Halol"],
            "Valsad": ["Valsad", "Bulsar", "Vapi", "Dharampur"],
        }
    },
    "Haryana": {
        "code": "HR",
        "districts": {
            "Ambala": ["Ambala", "Ambala Cantonment", "Barara", "Naraingarh"],
            "Bhiwani": ["Bhiwani", "Loharu", "Charkhi Dadri"],
            "Charkhi Dadri": ["Charkhi Dadri", "Badhra"],
            "Faridabad": ["Faridabad", "Ballabhgarh", "Palwal"],
            "Fatehabad": ["Fatehabad", "Ratia", "Tohana"],
            "Gurugram": ["Gurugram", "Manesar", "Badshahpur", "Sohna", "Pataudi"],
            "Hisar": ["Hisar", "Hansi", "Barwala", "Adampur"],
            "Jhajjar": ["Jhajjar", "Bahadurgarh", "Beri"],
            "Jind": ["Jind", "Narwana", "Safidon", "Uchana"],
            "Kaithal": ["Kaithal", "Cheeka", "Guhla"],
            "Karnal": ["Karnal", "Panipat", "Assandh", "Gharaunda", "Nilokheri"],
            "Kurukshetra": ["Kurukshetra", "Thanesar", "Pehowa", "Ladwa", "Shahabad"],
            "Mahendragarh": ["Narnaul", "Mahendragarh", "Ateli Mandi"],
            "Nuh": ["Nuh", "Taoru", "Firozpur Jhirka", "Punhana"],
            "Palwal": ["Palwal", "Hodal", "Hathin"],
            "Panchkula": ["Panchkula", "Kalka", "Morni", "Barwala"],
            "Panipat": ["Panipat", "Samalkha", "Israna"],
            "Rewari": ["Rewari", "Bawal", "Kosli"],
            "Rohtak": ["Rohtak", "Bahadurgarh", "Kalanaur"],
            "Sirsa": ["Sirsa", "Ellenabad", "Dabwali", "Rania"],
            "Sonipat": ["Sonipat", "Gohana", "Kharkhoda", "Rai"],
            "Yamunanagar": ["Yamunanagar", "Jagadhri", "Radaur", "Chhachhrauli"],
        }
    },
    "Himachal Pradesh": {
        "code": "HP",
        "districts": {
            "Bilaspur": ["Bilaspur", "Ghumarwin"],
            "Chamba": ["Chamba", "Dalhousie", "Bharmour"],
            "Hamirpur": ["Hamirpur", "Nadaun"],
            "Kangra": ["Dharamsala", "Palampur", "Nurpur", "Kangra", "Dehra Gopipur"],
            "Kinnaur": ["Reckong Peo"],
            "Kullu": ["Kullu", "Manali", "Mandi"],
            "Lahaul and Spiti": ["Keylong"],
            "Mandi": ["Mandi", "Sundernagar", "Jogindernagar"],
            "Shimla": ["Shimla", "Solan", "Rampur", "Nahan"],
            "Sirmaur": ["Nahan", "Paonta Sahib", "Rajgarh"],
            "Solan": ["Solan", "Baddi", "Nalagarh", "Kasauli"],
            "Una": ["Una", "Amb"],
        }
    },
    "Jharkhand": {
        "code": "JH",
        "districts": {
            "Bokaro": ["Bokaro", "Chas", "Phusro", "Gomoh"],
            "Chatra": ["Chatra", "Simaria"],
            "Deoghar": ["Deoghar", "Jasidih", "Madhupur"],
            "Dhanbad": ["Dhanbad", "Jharia", "Sindri", "Katras"],
            "Dumka": ["Dumka", "Shikaripara"],
            "East Singhbhum": ["Jamshedpur", "Dhalbhum", "Baharagora", "Ghatsila", "Boram"],
            "Garhwa": ["Garhwa", "Ranka"],
            "Giridih": ["Giridih", "Tundi", "Dumri"],
            "Godda": ["Godda", "Mahagama"],
            "Gumla": ["Gumla", "Sisai"],
            "Hazaribagh": ["Hazaribagh", "Ramgarh", "Barhi"],
            "Jamtara": ["Jamtara", "Nala"],
            "Khunti": ["Khunti", "Torpa"],
            "Koderma": ["Koderma", "Jhumri Tilaiya"],
            "Latehar": ["Latehar", "Mahuadanr"],
            "Lohardaga": ["Lohardaga", "Kuru"],
            "Pakur": ["Pakur", "Littipara"],
            "Palamu": ["Daltonganj", "Medininagar", "Lesliganj"],
            "Ramgarh": ["Ramgarh", "Mandu"],
            "Ranchi": ["Ranchi", "Hatia", "Namkum", "Kanke", "Bero"],
            "Sahebganj": ["Sahebganj", "Rajmahal", "Barhait"],
            "Saraikela Kharsawan": ["Saraikela", "Kharsawan", "Ichagarh"],
            "Simdega": ["Simdega", "Kolebira"],
            "West Singhbhum": ["Chaibasa", "Chakradharpur", "Jhinkpani"],
        }
    },
    "Karnataka": {
        "code": "KA",
        "districts": {
            "Bagalkot": ["Bagalkot", "Jamkhandi", "Mudhol", "Badami"],
            "Ballari": ["Ballari (Bellary)", "Hospet", "Kudligi", "Sandur"],
            "Belagavi": ["Belagavi (Belgaum)", "Dharwad", "Gokak", "Kittur"],
            "Bengaluru Rural": ["Doddaballapur", "Devanahalli", "Nelamangala"],
            "Bengaluru Urban": ["Bengaluru (Bangalore)", "Whitefield", "Electronic City", "Jayanagar", "Koramangala", "Indiranagar", "Hebbal", "Yeshwanthpur", "Malleswaram"],
            "Bidar": ["Bidar", "Bhalki", "Humnabad"],
            "Chamarajanagar": ["Chamarajanagar", "Kollegal", "Gundlupet"],
            "Chikkaballapur": ["Chikkaballapur", "Chintamani", "Sidlaghatta"],
            "Chikkamagaluru": ["Chikkamagaluru", "Kadur", "Tarikere", "Mudigere"],
            "Chitradurga": ["Chitradurga", "Hiriyur", "Holalkere"],
            "Dakshina Kannada": ["Mangaluru (Mangalore)", "Puttur", "Sullia", "Bantwal"],
            "Davanagere": ["Davanagere", "Harihar", "Harpanahalli", "Channagiri"],
            "Dharwad": ["Dharwad", "Hubballi (Hubli)", "Kalghatgi"],
            "Gadag": ["Gadag", "Ron", "Shirahatti"],
            "Hassan": ["Hassan", "Arakalagudu", "Belur", "Holenarasipur"],
            "Haveri": ["Haveri", "Ranebennur", "Savanur", "Hanagal"],
            "Kalaburagi": ["Kalaburagi (Gulbarga)", "Shahabad", "Yadgir"],
            "Kodagu": ["Madikeri", "Virajpet", "Somwarpet"],
            "Kolar": ["Kolar", "KGF (Kolar Gold Field)", "Malur", "Bangarpet"],
            "Koppal": ["Koppal", "Gangavathi", "Yelburga"],
            "Mandya": ["Mandya", "Krishnarajapet", "Maddur", "Pandavapura"],
            "Mysuru": ["Mysuru (Mysore)", "Nanjangud", "Krishnarajanagara", "Hunsur"],
            "Raichur": ["Raichur", "Lingasugur", "Manvi", "Sindhanur"],
            "Ramanagara": ["Ramanagara", "Channapatna", "Magadi", "Kanakapura"],
            "Shivamogga": ["Shivamogga (Shimoga)", "Sagar", "Bhadravati", "Sorab"],
            "Tumakuru": ["Tumakuru (Tumkur)", "Sira", "Madhugiri", "Tiptur"],
            "Udupi": ["Udupi", "Kundapura", "Karkal"],
            "Uttara Kannada": ["Karwar", "Sirsi", "Kumta", "Bhatkal"],
            "Vijayapura": ["Vijayapura (Bijapur)", "Sindagi", "Basavana Bagewadi"],
            "Yadgir": ["Yadgir", "Shorapur", "Raichur"],
        }
    },
    "Kerala": {
        "code": "KL",
        "districts": {
            "Alappuzha": ["Alappuzha (Alleppey)", "Chengannur", "Mavelikkara", "Kayamkulam"],
            "Ernakulam": ["Ernakulam", "Kochi", "Aluva", "Perumbavoor", "Angamaly", "Thrippunithura"],
            "Idukki": ["Idukki", "Kothamangalam", "Munnar", "Thodupuzha"],
            "Kannur": ["Kannur", "Thalassery", "Kuthuparamba", "Iritty"],
            "Kasaragod": ["Kasaragod", "Kanhangad", "Nileshwar"],
            "Kollam": ["Kollam", "Punalur", "Chavara", "Karunagappally"],
            "Kottayam": ["Kottayam", "Pala", "Changanacherry", "Ettumanoor"],
            "Kozhikode": ["Kozhikode (Calicut)", "Vatakara", "Koyilandy", "Quilandy"],
            "Malappuram": ["Malappuram", "Manjeri", "Tirur", "Perinthalmanna"],
            "Palakkad": ["Palakkad", "Ottapalam", "Shoranur", "Chittur"],
            "Pathanamthitta": ["Pathanamthitta", "Thiruvalla", "Adoor", "Pandalam"],
            "Thiruvananthapuram": ["Thiruvananthapuram", "Attingal", "Nedumangad", "Neyyattinkara"],
            "Thrissur": ["Thrissur", "Chalakudy", "Kodungallur", "Irinjalakuda"],
            "Wayanad": ["Kalpetta", "Mananthavady", "Sulthan Bathery"],
        }
    },
    "Madhya Pradesh": {
        "code": "MP",
        "districts": {
            "Agar Malwa": ["Agar Malwa", "Susner"],
            "Alirajpur": ["Alirajpur", "Jobat"],
            "Anuppur": ["Anuppur", "Shahdol"],
            "Ashoknagar": ["Ashoknagar", "Mungaoli"],
            "Balaghat": ["Balaghat", "Baihar", "Lalbarra"],
            "Barwani": ["Barwani", "Sendhwa", "Rajpur"],
            "Betul": ["Betul", "Sarni", "Multai"],
            "Bhind": ["Bhind", "Lahar", "Mehgaon"],
            "Bhopal": ["Bhopal", "Berasia", "Huzur", "Govindpura", "Kolar Road", "Arera Colony"],
            "Burhanpur": ["Burhanpur", "Nepanagar"],
            "Chhatarpur": ["Chhatarpur", "Khajuraho", "Bijawar", "Nowgong"],
            "Chhindwara": ["Chhindwara", "Parasia", "Sausar", "Pandhurna"],
            "Damoh": ["Damoh", "Hatta", "Jabera"],
            "Datia": ["Datia", "Bhander", "Seondha"],
            "Dewas": ["Dewas", "Kannod", "Sonkatch"],
            "Dhar": ["Dhar", "Manawar", "Kukshi", "Sardarpur"],
            "Dindori": ["Dindori", "Shahpura"],
            "Guna": ["Guna", "Chachoda", "Raghogarh"],
            "Gwalior": ["Gwalior", "Lashkar", "Morar", "Bhitarwar", "Dabra", "Antri"],
            "Harda": ["Harda", "Timarni"],
            "Hoshangabad": ["Hoshangabad", "Itarsi", "Sohagpur", "Pipariya"],
            "Indore": ["Indore", "Dewas", "Mhow", "Simrol", "Sanwer", "Palasia", "Vijay Nagar"],
            "Jabalpur": ["Jabalpur", "Katni", "Patan", "Sihora", "Panagar"],
            "Jhabua": ["Jhabua", "Petlawad", "Thandla"],
            "Katni": ["Katni", "Vijayraghavgarh", "Mudwara"],
            "Khandwa": ["Khandwa", "Burhanpur", "Mandhata"],
            "Khargone": ["Khargone", "Bhikangaon", "Maheshwar", "Barwaha"],
            "Mandla": ["Mandla", "Nainpur", "Bichhia"],
            "Mandsaur": ["Mandsaur", "Neemuch", "Sitamau"],
            "Morena": ["Morena", "Ambah", "Joura", "Sabalgarh"],
            "Narsinghpur": ["Narsinghpur", "Kareli", "Gadarwara"],
            "Neemuch": ["Neemuch", "Jawad", "Manasa"],
            "Niwari": ["Niwari", "Prithvipur"],
            "Panna": ["Panna", "Ajaygarh", "Pawai"],
            "Raisen": ["Raisen", "Bhopal", "Bareli", "Obaidullaganj"],
            "Rajgarh": ["Rajgarh", "Biaora", "Khilchipur"],
            "Ratlam": ["Ratlam", "Sailana", "Jaora", "Alot"],
            "Rewa": ["Rewa", "Mauganj", "Hanumana", "Sirmaur"],
            "Sagar": ["Sagar", "Banda", "Khurai", "Rehli"],
            "Satna": ["Satna", "Maihar", "Rewa", "Nagod"],
            "Sehore": ["Sehore", "Ashta", "Nasrullaganj"],
            "Seoni": ["Seoni", "Lakhnadon", "Barghat"],
            "Shahdol": ["Shahdol", "Umaria", "Beohari"],
            "Shajapur": ["Shajapur", "Shujalpur", "Kalapipal"],
            "Sheopur": ["Sheopur", "Vijaypur", "Karahal"],
            "Shivpuri": ["Shivpuri", "Pichhore", "Kolaras"],
            "Sidhi": ["Sidhi", "Rewa"],
            "Singrauli": ["Singrauli", "Waidhan"],
            "Tikamgarh": ["Tikamgarh", "Niwari", "Jatara"],
            "Ujjain": ["Ujjain", "Nagda", "Mahidpur", "Khachrod", "Barnagar"],
            "Umaria": ["Umaria", "Bandhogarh"],
            "Vidisha": ["Vidisha", "Ganj Basoda", "Sironj"],
        }
    },
    "Maharashtra": {
        "code": "MH",
        "districts": {
            "Ahmednagar": ["Ahmednagar", "Shrirampur", "Kopargaon", "Sangamner", "Manmad"],
            "Akola": ["Akola", "Washim", "Murtizapur", "Akot"],
            "Amravati": ["Amravati", "Achalpur", "Daryapur", "Morshi"],
            "Aurangabad": ["Aurangabad", "Jalna", "Paithan", "Sillod"],
            "Beed": ["Beed", "Ambejogai", "Georai", "Kaij"],
            "Bhandara": ["Bhandara", "Tumsar", "Pavni"],
            "Buldhana": ["Buldhana", "Khamgaon", "Malkapur", "Mehkar", "Chikhli"],
            "Chandrapur": ["Chandrapur", "Warora", "Ballarpur", "Rajura"],
            "Dhule": ["Dhule", "Shirpur", "Shahada"],
            "Gadchiroli": ["Gadchiroli", "Aheri", "Sironcha"],
            "Gondia": ["Gondia", "Tirora", "Arjuni Morgaon"],
            "Hingoli": ["Hingoli", "Sengaon"],
            "Jalgaon": ["Jalgaon", "Dhule", "Bhusawal", "Chopda", "Pachora"],
            "Jalna": ["Jalna", "Ambad", "Partur"],
            "Kolhapur": ["Kolhapur", "Ichalkaranji", "Sangli", "Kagal"],
            "Latur": ["Latur", "Udgir", "Nilanga"],
            "Mumbai City": ["Mumbai", "Byculla", "Chembur", "Colaba", "Dadar", "Kalyan", "Kurla", "Malad"],
            "Mumbai Suburban": ["Andheri", "Borivali", "Bandra", "Ghatkopar", "Kandivali", "Mulund", "Thane", "Vashi"],
            "Nagpur": ["Nagpur", "Kamptee", "Hingna", "Wardha", "Yavatmal"],
            "Nanded": ["Nanded", "Loha", "Mudkhed", "Hadgaon"],
            "Nandurbar": ["Nandurbar", "Navapur", "Shahada"],
            "Nashik": ["Nashik", "Malegaon", "Igatpuri", "Sinnar", "Ozar"],
            "Osmanabad": ["Osmanabad", "Tuljapur", "Paranda"],
            "Palghar": ["Palghar", "Vasai", "Virar", "Boisar", "Thane"],
            "Parbhani": ["Parbhani", "Pathri", "Gangakhed"],
            "Pune": ["Pune", "Pimpri-Chinchwad", "Hadapsar", "Kothrud", "Wakad", "Viman Nagar", "Hinjewadi", "Baner", "Lonavala"],
            "Raigad": ["Alibag", "Panvel", "Pen", "Uran", "Khopoli"],
            "Ratnagiri": ["Ratnagiri", "Chiplun", "Khed", "Dapoli"],
            "Sangli": ["Sangli", "Miraj", "Kolhapur", "Islampur", "Vita"],
            "Satara": ["Satara", "Karad", "Panchgani", "Koregaon"],
            "Sindhudurg": ["Sindhudurg", "Malvan", "Kudal", "Sawantwadi"],
            "Solapur": ["Solapur", "Pandharpur", "Bijapur", "Akkalkot", "Barshie"],
            "Thane": ["Thane", "Kalyan", "Dombivli", "Ulhasnagar", "Bhiwandi", "Navi Mumbai"],
            "Wardha": ["Wardha", "Hinganghat", "Arvi"],
            "Washim": ["Washim", "Mangrulpir"],
            "Yavatmal": ["Yavatmal", "Wardha", "Pusad", "Wani"],
        }
    },
    "Manipur": {
        "code": "MN",
        "districts": {
            "Bishnupur": ["Bishnupur", "Nambol"],
            "Chandel": ["Chandel"],
            "Churachandpur": ["Churachandpur"],
            "Imphal East": ["Imphal", "Porompat"],
            "Imphal West": ["Imphal", "Lamphelpat"],
            "Jiribam": ["Jiribam"],
            "Kakching": ["Kakching"],
            "Kamjong": ["Kamjong"],
            "Kangpokpi": ["Kangpokpi"],
            "Noney": ["Noney"],
            "Pherzawl": ["Pherzawl"],
            "Senapati": ["Senapati"],
            "Tamenglong": ["Tamenglong"],
            "Tengnoupal": ["Moreh"],
            "Thoubal": ["Thoubal", "Yairipok"],
            "Ukhrul": ["Ukhrul"],
        }
    },
    "Meghalaya": {
        "code": "ML",
        "districts": {
            "East Garo Hills": ["Williamnagar"],
            "East Jaintia Hills": ["Khliehriat"],
            "East Khasi Hills": ["Shillong", "Cherrapunji"],
            "North Garo Hills": ["Resubelpara"],
            "Ri Bhoi": ["Nongpoh"],
            "South Garo Hills": ["Baghmara"],
            "South West Garo Hills": ["Ampati"],
            "South West Khasi Hills": ["Mawkyrwat"],
            "West Garo Hills": ["Tura"],
            "West Jaintia Hills": ["Jowai"],
            "West Khasi Hills": ["Nongstoin"],
        }
    },
    "Mizoram": {
        "code": "MZ",
        "districts": {
            "Aizawl": ["Aizawl"],
            "Champhai": ["Champhai"],
            "Kolasib": ["Kolasib"],
            "Lawngtlai": ["Lawngtlai"],
            "Lunglei": ["Lunglei"],
            "Mamit": ["Mamit"],
            "Saiha": ["Saiha"],
            "Serchhip": ["Serchhip"],
        }
    },
    "Nagaland": {
        "code": "NL",
        "districts": {
            "Dimapur": ["Dimapur"],
            "Kohima": ["Kohima"],
            "Mokokchung": ["Mokokchung"],
            "Mon": ["Mon"],
            "Phek": ["Phek"],
            "Tuensang": ["Tuensang"],
            "Wokha": ["Wokha"],
            "Zunheboto": ["Zunheboto"],
        }
    },
    "Odisha": {
        "code": "OD",
        "districts": {
            "Angul": ["Angul", "Talcher", "Athamallik"],
            "Balangir": ["Balangir", "Titilagarh", "Patnagarh"],
            "Balasore": ["Balasore", "Bhadrak", "Jaleswar", "Nilagiri"],
            "Bargarh": ["Bargarh", "Padampur", "Barpali"],
            "Bhadrak": ["Bhadrak", "Basudevpur", "Dhamnagar"],
            "Boudh": ["Boudh", "Kantamal"],
            "Cuttack": ["Cuttack", "Athagarh", "Banki", "Choudwar"],
            "Deogarh": ["Deogarh", "Tileibani"],
            "Dhenkanal": ["Dhenkanal", "Kamakhyanagar"],
            "Gajapati": ["Paralakhemundi", "Mohana"],
            "Ganjam": ["Berhampur (Brahmapur)", "Aska", "Bhanjanagar", "Chhatrapur"],
            "Jagatsinghpur": ["Jagatsinghpur", "Paradip", "Balikuda"],
            "Jajpur": ["Jajpur", "Vyasanagar"],
            "Jharsuguda": ["Jharsuguda", "Belpahar"],
            "Kalahandi": ["Bhawanipatna", "Junagarh"],
            "Kandhamal": ["Phulbani", "Baliguda"],
            "Kendrapara": ["Kendrapara", "Patkura"],
            "Kendujhar": ["Kendujhar (Keonjhar)", "Anandapur"],
            "Khordha": ["Bhubaneswar", "Khordha", "Bhubaneswar Municipal", "Jatni", "Narasinghpur"],
            "Koraput": ["Koraput", "Jeypore", "Sunabeda"],
            "Malkangiri": ["Malkangiri", "Korkunda"],
            "Mayurbhanj": ["Baripada", "Rairangpur", "Udala"],
            "Nabarangpur": ["Nabarangpur", "Umerkote"],
            "Nayagarh": ["Nayagarh", "Odagaon"],
            "Nuapada": ["Nuapada", "Khariar"],
            "Puri": ["Puri", "Konark", "Nimapara"],
            "Rayagada": ["Rayagada", "Gunupur"],
            "Sambalpur": ["Sambalpur", "Jharsuguda", "Hirakud"],
            "Subarnapur": ["Sonepur", "Binka"],
            "Sundargarh": ["Sundargarh", "Rourkela", "Talsara"],
        }
    },
    "Punjab": {
        "code": "PB",
        "districts": {
            "Amritsar": ["Amritsar", "Attari", "Rajasansi"],
            "Barnala": ["Barnala", "Dhanaula"],
            "Bathinda": ["Bathinda", "Talwandi Sabo", "Rampura Phul"],
            "Faridkot": ["Faridkot", "Jaitu", "Kotkapura"],
            "Fatehgarh Sahib": ["Fatehgarh Sahib", "Amloh", "Bassi Pathana"],
            "Fazilka": ["Fazilka", "Abohar", "Jalalabad"],
            "Ferozepur": ["Ferozepur", "Zira", "Guru Har Sahai"],
            "Gurdaspur": ["Gurdaspur", "Batala", "Dhariwal", "Pathankot"],
            "Hoshiarpur": ["Hoshiarpur", "Dasuya", "Mukerian"],
            "Jalandhar": ["Jalandhar", "Nakodar", "Phagwara", "Phillaur"],
            "Kapurthala": ["Kapurthala", "Phagwara", "Sultanpur Lodhi"],
            "Ludhiana": ["Ludhiana", "Khanna", "Moga", "Samrala", "Raikot"],
            "Malerkotla": ["Malerkotla"],
            "Mansa": ["Mansa", "Sardulgarh"],
            "Moga": ["Moga", "Nihal Singh Wala"],
            "Mohali (SAS Nagar)": ["Mohali", "Dera Bassi", "Kharar", "Zirakpur", "Ropar"],
            "Muktsar": ["Muktsar", "Malout", "Gidderbaha"],
            "Nawanshahr": ["Nawanshahr (Shaheed Bhagat Singh Nagar)", "Balachaur"],
            "Pathankot": ["Pathankot", "Dhar Kalan"],
            "Patiala": ["Patiala", "Rajpura", "Nabha", "Samana"],
            "Rupnagar": ["Rupnagar", "Anandpur Sahib", "Kiratpur Sahib"],
            "Sangrur": ["Sangrur", "Sunam", "Moonak", "Lehra Gaga"],
            "Tarn Taran": ["Tarn Taran", "Patti", "Khem Karan"],
        }
    },
    "Rajasthan": {
        "code": "RJ",
        "districts": {
            "Ajmer": ["Ajmer", "Pushkar", "Kishangarh", "Beawar", "Nasirabad"],
            "Alwar": ["Alwar", "Bharatpur", "Behror", "Neemrana", "Rajgarh"],
            "Banswara": ["Banswara", "Kushalgarh"],
            "Baran": ["Baran", "Anta", "Chhipabarod"],
            "Barmer": ["Barmer", "Balotra"],
            "Bharatpur": ["Bharatpur", "Deeg", "Kaman"],
            "Bhilwara": ["Bhilwara", "Shahpura", "Mandalgarh"],
            "Bikaner": ["Bikaner", "Nokha", "Deshnoke"],
            "Bundi": ["Bundi", "Hindoli", "Nainwa"],
            "Chittorgarh": ["Chittorgarh", "Nimbahera", "Bari Sadri"],
            "Churu": ["Churu", "Sardarshahar", "Sujangarh"],
            "Dausa": ["Dausa", "Bandikui", "Sikrai"],
            "Dholpur": ["Dholpur", "Bari", "Rajakhera"],
            "Dungarpur": ["Dungarpur", "Sagwara"],
            "Hanumangarh": ["Hanumangarh", "Nohar", "Bhadra", "Tibbi"],
            "Jaipur": ["Jaipur", "Jaipur Rural", "Sanganer", "Vidhyadhar Nagar", "Vaishali Nagar", "Mansarovar", "Tonk Road", "Sikar Road"],
            "Jaisalmer": ["Jaisalmer", "Pokaran"],
            "Jalore": ["Jalore", "Ahore", "Sirohi"],
            "Jhalawar": ["Jhalawar", "Jhalarapatan", "Khanpur"],
            "Jhunjhunu": ["Jhunjhunu", "Pilani", "Chirawa"],
            "Jodhpur": ["Jodhpur", "Pali", "Barli", "Bilara"],
            "Karauli": ["Karauli", "Hindaun"],
            "Kota": ["Kota", "Baran", "Chhipabarod"],
            "Nagaur": ["Nagaur", "Makrana", "Didwana"],
            "Pali": ["Pali", "Bali", "Marwar Junction", "Sumerpur"],
            "Pratapgarh": ["Pratapgarh", "Arnod"],
            "Rajsamand": ["Rajsamand", "Nathdwara"],
            "Sawai Madhopur": ["Sawai Madhopur", "Gangapur City"],
            "Sikar": ["Sikar", "Fatehpur", "Neem Ka Thana"],
            "Sirohi": ["Sirohi", "Abu Road", "Mount Abu"],
            "Sri Ganganagar": ["Sri Ganganagar", "Suratgarh", "Anupgarh"],
            "Tonk": ["Tonk", "Uniara", "Newai"],
            "Udaipur": ["Udaipur", "Nathdwara", "Rajsamand", "Bhilwara"],
        }
    },
    "Sikkim": {
        "code": "SK",
        "districts": {
            "East Sikkim": ["Gangtok", "Rumtek", "Pakyong"],
            "North Sikkim": ["Mangan", "Chungthang"],
            "South Sikkim": ["Namchi", "Jorethang"],
            "West Sikkim": ["Gyalshing (Geyzing)", "Pelling"],
        }
    },
    "Tamil Nadu": {
        "code": "TN",
        "districts": {
            "Ariyalur": ["Ariyalur", "Jayankondam"],
            "Chennai": ["Chennai", "Adyar", "Anna Nagar", "Egmore", "Guindy", "Kodambakkam", "Perambur", "T. Nagar", "Velachery", "Tambaram"],
            "Chengalpattu": ["Chengalpattu", "Tambaram", "Maduranthakam"],
            "Coimbatore": ["Coimbatore", "Tirupur", "Pollachi", "Mettupalayam"],
            "Cuddalore": ["Cuddalore", "Chidambaram", "Virudhachalam", "Panruti"],
            "Dharmapuri": ["Dharmapuri", "Krishnagiri"],
            "Dindigul": ["Dindigul", "Palani", "Kodaikanal", "Natham"],
            "Erode": ["Erode", "Bhavani", "Tirupur", "Perundurai"],
            "Kallakurichi": ["Kallakurichi", "Ulundurpet"],
            "Kanchipuram": ["Kanchipuram", "Kancheepuram"],
            "Kanyakumari": ["Nagercoil", "Kuzhithurai", "Colachel"],
            "Karur": ["Karur", "Kulithalai", "Aravakurichi"],
            "Krishnagiri": ["Krishnagiri", "Hosur", "Denkanikotai"],
            "Madurai": ["Madurai", "Melur", "Dindigul", "Sivaganga"],
            "Mayiladuthurai": ["Mayiladuthurai", "Sirkazhi"],
            "Nagapattinam": ["Nagapattinam", "Vedaranyam", "Kilvelur"],
            "Namakkal": ["Namakkal", "Rasipuram", "Tiruchengode"],
            "Nilgiris": ["Ooty (Udagamandalam)", "Coonoor", "Kotagiri"],
            "Perambalur": ["Perambalur", "Ariyalur"],
            "Pudukkottai": ["Pudukkottai", "Aranthangi"],
            "Ramanathapuram": ["Ramanathapuram", "Rameswaram", "Paramakudi"],
            "Ranipet": ["Ranipet", "Arcot", "Walajah"],
            "Salem": ["Salem", "Omalur", "Mettur", "Attur"],
            "Sivaganga": ["Sivaganga", "Karaikudi", "Tiruppattur"],
            "Tenkasi": ["Tenkasi", "Sankarankovil"],
            "Thanjavur": ["Thanjavur", "Kumbakonam", "Papanasam"],
            "Theni": ["Theni", "Bodi", "Uthamapalayam"],
            "Thoothukudi": ["Thoothukudi (Tuticorin)", "Kovilpatti", "Tiruchendur"],
            "Tiruchirappalli": ["Tiruchirappalli (Trichy)", "Srirangam", "Lalgudi"],
            "Tirunelveli": ["Tirunelveli", "Palayamkottai", "Ambasamudram"],
            "Tirupathur": ["Tirupathur", "Ambur", "Vaniyambadi"],
            "Tiruppur": ["Tiruppur (Tirupur)", "Palladam", "Avinashi"],
            "Tiruvallur": ["Tiruvallur", "Poonamallee", "Thiruvottiyur", "Avadi"],
            "Tiruvannamalai": ["Tiruvannamalai", "Arni", "Chengam", "Polur"],
            "Tiruvarur": ["Tiruvarur", "Kumbakonam", "Mannargudi"],
            "Vellore": ["Vellore", "Katpadi", "Ranipet", "Sholinghur"],
            "Viluppuram": ["Viluppuram", "Tindivanam", "Gingee"],
            "Virudhunagar": ["Virudhunagar", "Sivakasi", "Rajapalayam", "Sattur"],
        }
    },
    "Telangana": {
        "code": "TS",
        "districts": {
            "Adilabad": ["Adilabad", "Nirmal"],
            "Bhadradri Kothagudem": ["Kothagudem", "Bhadrachalam"],
            "Hyderabad": ["Hyderabad", "Secunderabad", "Banjara Hills", "Jubilee Hills", "Kukatpally", "HITEC City", "Gachibowli", "Madhapur", "Ameerpet"],
            "Jagtial": ["Jagtial", "Metpally"],
            "Jangaon": ["Jangaon"],
            "Jayashankar Bhupalpally": ["Bhupalpally"],
            "Jogulamba Gadwal": ["Gadwal"],
            "Kamareddy": ["Kamareddy", "Banswada"],
            "Karimnagar": ["Karimnagar", "Huzurabad", "Jagtial"],
            "Khammam": ["Khammam", "Kothagudem", "Sattupalli"],
            "Kumuram Bheem Asifabad": ["Asifabad"],
            "Mahabubabad": ["Mahabubabad"],
            "Mahabubnagar": ["Mahabubnagar", "Jadcherla", "Narayanpet", "Kollapur"],
            "Mancherial": ["Mancherial", "Bellampalli"],
            "Medak": ["Medak", "Sangareddy", "Zaheerabad"],
            "Medchal-Malkajgiri": ["Medchal", "Malkajgiri", "Keesara", "Ghatkesar"],
            "Mulugu": ["Mulugu", "Bhupalpally"],
            "Nagarkurnool": ["Nagarkurnool"],
            "Nalgonda": ["Nalgonda", "Miryalaguda", "Bhongir"],
            "Narayanpet": ["Narayanpet"],
            "Nirmal": ["Nirmal", "Bhainsa", "Dichpally"],
            "Nizamabad": ["Nizamabad", "Armoor", "Bodhan"],
            "Peddapalli": ["Peddapalli", "Ramagundam", "Manthani"],
            "Rajanna Sircilla": ["Sircilla"],
            "Ranga Reddy": ["Rangareddy", "LB Nagar", "Saroornagar", "Shamshabad", "Hayathnagar"],
            "Sangareddy": ["Sangareddy", "Zaheerabad"],
            "Siddipet": ["Siddipet", "Gajwel"],
            "Suryapet": ["Suryapet", "Nalgonda"],
            "Vikarabad": ["Vikarabad", "Pudur"],
            "Wanaparthy": ["Wanaparthy"],
            "Warangal Rural": ["Warangal"],
            "Warangal Urban": ["Warangal", "Hanamkonda", "Kazipet"],
            "Yadadri Bhuvanagiri": ["Bhongir"],
        }
    },
    "Tripura": {
        "code": "TR",
        "districts": {
            "Dhalai": ["Ambassa", "Kamalpur"],
            "Gomati": ["Udaipur", "Sonamura"],
            "Khowai": ["Khowai", "Teliamura"],
            "North Tripura": ["Dharmanagar", "Kanchanpur"],
            "Sepahijala": ["Bishalgarh", "Sonamura"],
            "Sipahijala": ["Sepahijala"],
            "South Tripura": ["Belonia", "Sabroom"],
            "Unakoti": ["Kailashahar"],
            "West Tripura": ["Agartala", "Badharghat"],
        }
    },
    "Uttar Pradesh": {
        "code": "UP",
        "districts": {
            "Agra": ["Agra", "Firozabad", "Shamshabad", "Fatehabad", "Sikandra"],
            "Aligarh": ["Aligarh", "Hathras", "Khurja", "Bulandshahr"],
            "Allahabad": ["Prayagraj (Allahabad)", "Phulpur", "Chail"],
            "Ambedkar Nagar": ["Akbarpur", "Tanda"],
            "Amethi": ["Amethi", "Gauriganj", "Salon"],
            "Amroha": ["Amroha", "Dhanaura", "Hasanpur"],
            "Auraiya": ["Auraiya", "Dibiyapur"],
            "Ayodhya": ["Ayodhya (Faizabad)", "Sohawal", "Tanda"],
            "Azamgarh": ["Azamgarh", "Mau", "Phulpur"],
            "Baghpat": ["Baghpat", "Baraut", "Pilana"],
            "Bahraich": ["Bahraich", "Nanpara"],
            "Ballia": ["Ballia", "Rasra"],
            "Balrampur": ["Balrampur", "Utraula"],
            "Banda": ["Banda", "Naraini"],
            "Barabanki": ["Barabanki", "Fatehpur", "Haidergarh"],
            "Bareilly": ["Bareilly", "Pilibhit", "Baheri", "Nawabganj"],
            "Basti": ["Basti", "Khalilabad", "Harraiya"],
            "Bijnor": ["Bijnor", "Nagina", "Chandpur"],
            "Budaun": ["Budaun", "Sahaswan", "Bilsi"],
            "Bulandshahr": ["Bulandshahr", "Khurja", "Sikandrabad"],
            "Chandauli": ["Chandauli", "Mughalsarai (Pandit Deen Dayal Upadhyaya Nagar)"],
            "Chitrakoot": ["Chitrakoot", "Karwi"],
            "Deoria": ["Deoria", "Bhatpar Rani"],
            "Etah": ["Etah", "Kasganj"],
            "Etawah": ["Etawah", "Saifai"],
            "Farrukhabad": ["Fatehgarh", "Farrukhabad"],
            "Fatehpur": ["Fatehpur", "Bindki"],
            "Firozabad": ["Firozabad", "Shikohabad", "Tundla"],
            "Gautam Buddha Nagar": ["Noida", "Greater Noida", "Dadri"],
            "Ghaziabad": ["Ghaziabad", "Loni", "Modinagar", "Muradnagar", "Kavinagar"],
            "Ghazipur": ["Ghazipur", "Saidpur", "Zamania"],
            "Gonda": ["Gonda", "Nawabganj", "Mankapur"],
            "Gorakhpur": ["Gorakhpur", "Deoria", "Kushinagar"],
            "Hamirpur": ["Hamirpur", "Maudaha"],
            "Hapur": ["Hapur", "Pilakhua"],
            "Hardoi": ["Hardoi", "Sandila"],
            "Hathras": ["Hathras", "Aligarh"],
            "Jalaun": ["Jalaun", "Orai"],
            "Jaunpur": ["Jaunpur", "Shahganj", "Mungra Badshahpur"],
            "Jhansi": ["Jhansi", "Lalitpur", "Mauranipur"],
            "Kannauj": ["Kannauj", "Tindwari"],
            "Kanpur Dehat": ["Akbarpur", "Purwa"],
            "Kanpur Nagar": ["Kanpur", "Govindnagar", "Armapur", "Panki"],
            "Kasganj": ["Kasganj", "Soron"],
            "Kaushambi": ["Koshambi", "Manjhanpur"],
            "Kushinagar": ["Kushinagar", "Padrauna"],
            "Lakhimpur Kheri": ["Lakhimpur", "Kheri", "Pallia Kalan"],
            "Lalitpur": ["Lalitpur", "Mahrauni"],
            "Lucknow": ["Lucknow", "Mahanagar", "Gomti Nagar", "Hazratganj", "Alambagh", "Aliganj", "Vibhuti Khand"],
            "Maharajganj": ["Maharajganj", "Sonauli"],
            "Mahoba": ["Mahoba", "Charkhari"],
            "Mainpuri": ["Mainpuri", "Shikohabad"],
            "Mathura": ["Mathura", "Vrindavan", "Goverdhan"],
            "Mau": ["Mau", "Ghosi", "Madhuban"],
            "Meerut": ["Meerut", "Mawana", "Hapur", "Modinagar"],
            "Mirzapur": ["Mirzapur", "Chunar", "Vindhyachal"],
            "Moradabad": ["Moradabad", "Rampur", "Amroha"],
            "Muzaffarnagar": ["Muzaffarnagar", "Khatauli", "Shamli"],
            "Pilibhit": ["Pilibhit", "Bisalpur", "Puranpur"],
            "Pratapgarh": ["Pratapgarh", "Kunda"],
            "Prayagraj": ["Prayagraj (Allahabad)", "Naini", "Phaphamau", "Jhunsi"],
            "Raebareli": ["Raebareli", "Lalganj", "Amethi"],
            "Rampur": ["Rampur", "Bilaspur", "Milak"],
            "Saharanpur": ["Saharanpur", "Deoband", "Nakur"],
            "Sambhal": ["Sambhal", "Chandausi"],
            "Sant Kabir Nagar": ["Khalilabad", "Mehdawal"],
            "Siddharth Nagar": ["Siddharth Nagar", "Bhanwapur"],
            "Sitapur": ["Sitapur", "Mahmudabad", "Biswan"],
            "Sonbhadra": ["Sonbhadra", "Chopan", "Obra"],
            "Sultanpur": ["Sultanpur", "Lambhua"],
            "Unnao": ["Unnao", "Kanpur"],
            "Varanasi": ["Varanasi", "Ramnagar", "Mughalserai", "Shivpur"],
        }
    },
    "Uttarakhand": {
        "code": "UK",
        "districts": {
            "Almora": ["Almora", "Ranikhet", "Someshwar"],
            "Bageshwar": ["Bageshwar", "Kanda"],
            "Chamoli": ["Gopeshwar (Chamoli)", "Joshimath", "Karnaprayag"],
            "Champawat": ["Champawat", "Tanakpur"],
            "Dehradun": ["Dehradun", "Rishikesh", "Mussoorie", "Doiwala", "Vikasnagar"],
            "Haridwar": ["Haridwar", "Roorkee", "Laksar", "Manglaur"],
            "Nainital": ["Halwani", "Kathgodam", "Nainital", "Ramnagar"],
            "Pauri Garhwal": ["Pauri", "Kotdwara", "Lansdowne"],
            "Pithoragarh": ["Pithoragarh", "Dharchula"],
            "Rudraprayag": ["Rudraprayag", "Agastmuni"],
            "Tehri Garhwal": ["New Tehri", "Dhanolti"],
            "Udham Singh Nagar": ["Rudrapur", "Kashipur", "Jaspur", "Sitarganj", "Kichha"],
            "Uttarkashi": ["Uttarkashi", "Barkot"],
        }
    },
    "West Bengal": {
        "code": "WB",
        "districts": {
            "Alipurduar": ["Alipurduar", "Falakata", "Madarihat"],
            "Bankura": ["Bankura", "Bishnupur", "Barjora"],
            "Birbhum": ["Suri", "Bolpur", "Rampurhat"],
            "Cooch Behar": ["Cooch Behar", "Tufanganj", "Dinhata"],
            "Dakshin Dinajpur": ["Balurghat", "Gangarampur"],
            "Darjeeling": ["Darjeeling", "Siliguri", "Kurseong", "Kalimpong"],
            "Hooghly": ["Chinsurah", "Chandannagar", "Shreempur", "Uttarpara", "Arambagh"],
            "Howrah": ["Howrah", "Uluberia", "Bally", "Santragachi"],
            "Jalpaiguri": ["Jalpaiguri", "Dhupguri", "Maynaguri"],
            "Jhargram": ["Jhargram", "Salboni"],
            "Kalimpong": ["Kalimpong", "Gorubathan"],
            "Kolkata": ["Kolkata", "Tollygunge", "Park Street", "Salt Lake", "New Town", "Jadavpur", "Behala"],
            "Malda": ["Malda", "Old Malda", "English Bazar"],
            "Murshidabad": ["Berhampore", "Jangipur", "Lalbagh", "Jiaganj"],
            "Nadia": ["Krishnanagar", "Ranaghat", "Kalyani", "Shantipur"],
            "North 24 Parganas": ["Barasat", "Dum Dum", "Habra", "Bongaon", "Barrackpore", "Basirhat"],
            "Paschim Bardhaman": ["Asansol", "Durgapur", "Raniganj", "Kulti"],
            "Paschim Medinipur": ["Midnapore", "Kharagpur", "Jhargram", "Ghatal"],
            "Purba Bardhaman": ["Bardhaman", "Katwa"],
            "Purba Medinipur": ["Contai", "Tamluk", "Mecheda", "Haldia"],
            "Purulia": ["Purulia", "Jhalda", "Raghunathpur"],
            "South 24 Parganas": ["Alipore", "Diamond Harbour", "Kakdwip", "Budge Budge", "Baruipur"],
            "Uttar Dinajpur": ["Raiganj", "Islampur", "Dalkhola"],
        }
    },
    # Union Territories
    "Andaman and Nicobar Islands": {
        "code": "AN",
        "districts": {
            "Nicobar": ["Car Nicobar"],
            "North and Middle Andaman": ["Mayabunder", "Diglipur"],
            "South Andaman": ["Port Blair"],
        }
    },
    "Chandigarh": {
        "code": "CH",
        "districts": {
            "Chandigarh": ["Chandigarh", "Sector 17", "Sector 22", "Sector 34", "Manimajra", "Panchkula"],
        }
    },
    "Dadra and Nagar Haveli and Daman and Diu": {
        "code": "DD",
        "districts": {
            "Dadra and Nagar Haveli": ["Silvassa"],
            "Daman": ["Daman"],
            "Diu": ["Diu"],
        }
    },
    "Delhi": {
        "code": "DL",
        "districts": {
            "Central Delhi": ["Connaught Place", "Karol Bagh","Paharganj", "Rajendra Nagar"],
            "East Delhi": ["Laxmi Nagar", "Preet Vihar", "Shahdara", "Vivek Vihar", "Patparganj"],
            "New Delhi": ["New Delhi", "Chanakyapuri", "Sarojini Nagar", "Khan Market", "Lajpat Nagar"],
            "North Delhi": ["Ashok Nagar", "Civil Lines", "Sadar Bazar", "Burari"],
            "North East Delhi": ["Bhajanpura", "Mustafabad", "Nand Nagri", "Seelampur"],
            "North West Delhi": ["Rohini", "Pitampura", "Shalimar Bagh", "Rani Bagh", "Kanjhawala"],
            "Shahdara": ["Shahdara", "Dilshad Garden", "Mansarovar Park"],
            "South Delhi": ["Greater Kailash", "Hauz Khas", "Mehrauli", "Malviya Nagar", "Saket"],
            "South East Delhi": ["Defence Colony", "Jangpura", "Lajpat Nagar", "Nizamuddin"],
            "South West Delhi": ["Dwarka", "Janakpuri", "Vikaspuri", "Uttam Nagar", "Najafgarh"],
            "West Delhi": ["Punjabi Bagh", "Rajouri Garden", "Tilak Nagar", "Subhash Nagar"],
        }
    },
    "Jammu and Kashmir": {
        "code": "JK",
        "districts": {
            "Anantnag": ["Anantnag", "Pahalgam", "Kokernag"],
            "Bandipora": ["Bandipora", "Gurez"],
            "Baramulla": ["Baramulla", "Sopore", "Pattan"],
            "Budgam": ["Budgam", "Beerwah"],
            "Doda": ["Doda", "Bhaderwah"],
            "Ganderbal": ["Ganderbal", "Kangan"],
            "Jammu": ["Jammu", "Samba", "Vijaypur", "Kathua"],
            "Kathua": ["Kathua", "Hiranagar", "Billawar"],
            "Kishtwar": ["Kishtwar", "Padder"],
            "Kulgam": ["Kulgam", "Devsar"],
            "Kupwara": ["Kupwara", "Handwara"],
            "Poonch": ["Poonch", "Surankote"],
            "Pulwama": ["Pulwama", "Awantipora"],
            "Rajouri": ["Rajouri", "Nowshera"],
            "Ramban": ["Ramban", "Banihal"],
            "Reasi": ["Reasi", "Mahore"],
            "Samba": ["Samba", "Vijaypur"],
            "Shopian": ["Shopian", "Kellar"],
            "Srinagar": ["Srinagar", "Badami Bagh", "Lal Chowk", "Rajbagh"],
            "Udhampur": ["Udhampur", "Ramnagar"],
        }
    },
    "Ladakh": {
        "code": "LA",
        "districts": {
            "Kargil": ["Kargil", "Zanskar", "Drass"],
            "Leh": ["Leh", "Nubra", "Changthang"],
        }
    },
    "Lakshadweep": {
        "code": "LD",
        "districts": {
            "Lakshadweep": ["Kavaratti", "Agatti", "Minicoy"],
        }
    },
    "Puducherry": {
        "code": "PY",
        "districts": {
            "Karikal": ["Karaikal"],
            "Mahe": ["Mahe"],
            "Puducherry": ["Puducherry (Pondicherry)", "Villianur", "Ariyankuppam"],
            "Yanam": ["Yanam"],
        }
    },
}

# Sample pincodes for major cities (subset)
SAMPLE_PINCODES = {
    "Bhopal": [("462001", ["New Market", "Arera Colony"]), ("462003", ["Kolar Road", "Bag Sewania"]), ("462026", ["Govindpura", "Mandideep"])],
    "Balaghat": [("481001", ["Balaghat City", "Gugulari"])],
    "Baihar": [("481111", ["Baihar Town", "Sarekha"])],
    "Indore": [("452001", ["Sarwate Bus Stand", "MG Road"]), ("452010", ["Vijay Nagar", "AB Road"]), ("452016", ["Palasia", "Janjeerwala Square"])],
    "Gwalior": [("474001", ["City Centre", "Lashkar"]), ("474002", ["Morar", "University Road"])],
    "Jabalpur": [("482001", ["Wright Town", "Napier Town"]), ("482002", ["Adhartal", "Garha"])],
    "Lucknow": [("226001", ["Hazratganj", "Mahatma Gandhi Marg"]), ("226010", ["Gomti Nagar", "Vibhuti Khand"]), ("226020", ["Alambagh", "Aashiana"])],
    "Kanpur": [("208001", ["Mall Road", "Civil Lines"]), ("208012", ["Govindnagar", "Armapur"])],
    "Varanasi": [("221001", ["Godaulia", "Dashashwamedh Ghat"]), ("221002", ["Lanka", "BHU Campus"])],
    "Prayagraj": [("211001", ["Civil Lines", "MG Marg"]), ("211002", ["George Town", "Katra"])],
    "Jaipur": [("302001", ["MI Road", "Badi Chaupar"]), ("302017", ["Vaishali Nagar", "Shyam Nagar"]), ("302020", ["Mansarovar", "New Sanganer Road"])],
    "Jodhpur": [("342001", ["Station Road", "Sadar Bazar"]), ("342003", ["Ratanada", "Shastri Nagar"])],
    "Udaipur": [("313001", ["City Lake", "Chetak Circle"]), ("313002", ["Pratap Nagar", "Sukhadia Circle"])],
    "Mumbai": [("400001", ["Churchgate", "Nariman Point"]), ("400051", ["Bandra West", "Linking Road"]), ("400076", ["Andheri East", "MIDC"])],
    "Pune": [("411001", ["Shivajinagar", "FC Road"]), ("411045", ["Hinjewadi", "Phase 1"]), ("411006", ["Camp", "Bhavani Peth"])],
    "Bengaluru": [("560001", ["MG Road", "Brigade Road"]), ("560066", ["Electronic City", "Phase 1"]), ("560037", ["Koramangala", "5th Block"])],
    "Chennai": [("600001", ["George Town", "Parry's"]), ("600017", ["T Nagar", "Pondy Bazaar"]), ("600096", ["Velachery", "Vijayanagar"])],
    "Hyderabad": [("500001", ["Charminar", "Laad Bazar"]), ("500081", ["HITEC City", "Madhapur"]), ("500034", ["Banjara Hills", "Road No. 12"])],
    "Kolkata": [("700001", ["BBD Bag", "Dalhousie"]), ("700029", ["Tollygunge", "Prince Anwar Shah"]), ("700064", ["Salt Lake", "Sector V"])],
    "Delhi": [("110001", ["Connaught Place", "Janpath"]), ("110019", ["Hauz Khas", "Green Park"]), ("110075", ["Dwarka", "Sector 12"])],
    "Ahmedabad": [("380001", ["Ellis Bridge", "Ashram Road"]), ("380058", ["Bopal", "S.G. Highway"]), ("380013", ["Naranpura", "Vijay Char Rasta"])],
    "Surat": [("395001", ["Rander Road", "Ring Road"]), ("395007", ["Adajan", "Piplod"]), ("395006", ["Dumas Road", "Vesu"])],
    "Nagpur": [("440001", ["Dharampeth", "Sitabuldi"]), ("440010", ["Mankapur", "Hingna Road"])],
    "Noida": [("201301", ["Sector 18", "Atta Market"]), ("201304", ["Sector 62", "H Block"]), ("201306", ["Greater Noida", "Gamma"])],
    "Gurgaon": [("122001", ["MG Road", "Sikanderpur"]), ("122002", ["DLF Phase 1", "Gurugram"]), ("122018", ["Sector 56", "Golf Course Road"])],
}


class Command(BaseCommand):
    help = 'Seed India address master data (Country, States, Districts, Cities, Pincodes, Areas)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing location data before seeding',
        )
        parser.add_argument(
            '--pincodes',
            action='store_true',
            default=True,
            help='Also seed sample pincodes and areas for major cities',
        )

    def handle(self, *args, **options):
        from location_master.models import Country, State, District, City, Pincode, Area

        start = time.time()

        if options['clear']:
            self.stdout.write('Clearing existing location data...')
            Area.objects.all().delete()
            Pincode.objects.all().delete()
            City.objects.all().delete()
            District.objects.all().delete()
            State.objects.all().delete()
            Country.objects.all().delete()
            self.stdout.write(self.style.WARNING('Cleared all location data.'))

        self.stdout.write('Creating Country: India...')
        india, _ = Country.objects.get_or_create(
            code='IN',
            defaults={'name': 'India'}
        )

        total_states = total_districts = total_cities = 0

        with transaction.atomic():
            for state_name, state_info in INDIA_DATA.items():
                state, created = State.objects.get_or_create(
                    country=india,
                    name=state_name,
                    defaults={'code': state_info['code']}
                )
                if created:
                    total_states += 1

                for district_name, cities in state_info['districts'].items():
                    district, created = District.objects.get_or_create(
                        state=state,
                        name=district_name,
                    )
                    if created:
                        total_districts += 1

                    for city_name in cities:
                        _, created = City.objects.get_or_create(
                            district=district,
                            name=city_name,
                        )
                        if created:
                            total_cities += 1

        self.stdout.write(self.style.SUCCESS(
            f'[OK] Seeded: {total_states} states, {total_districts} districts, {total_cities} cities'
        ))

        # Seed pincodes and areas for major cities
        total_pincodes = total_areas = 0
        with transaction.atomic():
            for city_name, pincodes in SAMPLE_PINCODES.items():
                city_qs = City.objects.filter(name=city_name)
                if not city_qs.exists():
                    continue
                city_obj = city_qs.first()
                for pincode_code, areas in pincodes:
                    pincode, created = Pincode.objects.get_or_create(
                        city=city_obj, code=pincode_code
                    )
                    if created:
                        total_pincodes += 1
                    for area_name in areas:
                        _, created = Area.objects.get_or_create(
                            pincode=pincode, name=area_name
                        )
                        if created:
                            total_areas += 1

        elapsed = round(time.time() - start, 2)
        self.stdout.write(self.style.SUCCESS(
            f'[OK] Also seeded: {total_pincodes} pincodes, {total_areas} areas in {elapsed}s'
        ))
        self.stdout.write(self.style.SUCCESS('[DONE] India address data seeding complete!'))
