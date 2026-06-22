"""
Management command to seed USA address master data.
Usage: python manage.py seed_usa_address
       python manage.py seed_usa_address --clear   (clears existing data first)
"""
import time
from django.core.management.base import BaseCommand
from django.db import transaction

# ============================================================
# USA MASTER DATA
# Hierarchy: Country → State → County → City → ZipCode → Area
# ============================================================

USA_DATA = {
    "Alabama": {
        "code": "AL",
        "districts": {
            "Jefferson County": ["Birmingham", "Bessemer", "Hoover", "Homewood"],
            "Mobile County": ["Mobile", "Prichard", "Saraland"],
            "Madison County": ["Huntsville", "Madison", "Meridianville"],
            "Montgomery County": ["Montgomery", "Pike Road"],
            "Tuscaloosa County": ["Tuscaloosa", "Northport"],
            "Shelby County": ["Pelham", "Helena", "Chelsea", "Alabaster"],
        }
    },
    "Alaska": {
        "code": "AK",
        "districts": {
            "Anchorage Municipality": ["Anchorage", "Eagle River"],
            "Fairbanks North Star Borough": ["Fairbanks", "North Pole"],
            "Matanuska-Susitna Borough": ["Wasilla", "Palmer"],
            "Kenai Peninsula Borough": ["Kenai", "Soldotna", "Homer"],
        }
    },
    "Arizona": {
        "code": "AZ",
        "districts": {
            "Maricopa County": ["Phoenix", "Scottsdale", "Tempe", "Mesa", "Glendale", "Chandler", "Gilbert"],
            "Pima County": ["Tucson", "Marana", "Sahuarita"],
            "Pinal County": ["Casa Grande", "Apache Junction", "Maricopa"],
            "Yavapai County": ["Prescott", "Prescott Valley", "Cottonwood"],
            "Cochise County": ["Sierra Vista", "Douglas", "Bisbee"],
        }
    },
    "Arkansas": {
        "code": "AR",
        "districts": {
            "Pulaski County": ["Little Rock", "North Little Rock", "Maumelle", "Jacksonville"],
            "Benton County": ["Bentonville", "Rogers", "Bella Vista", "Fayetteville"],
            "Washington County": ["Fayetteville", "Springdale", "Farmington"],
            "Garland County": ["Hot Springs", "Hot Springs Village"],
            "Sebastian County": ["Fort Smith", "Greenwood"],
        }
    },
    "California": {
        "code": "CA",
        "districts": {
            "Los Angeles County": ["Los Angeles", "Long Beach", "Glendale", "Santa Clarita", "Pasadena", "Torrance"],
            "San Diego County": ["San Diego", "Chula Vista", "Oceanside", "Escondido", "El Cajon"],
            "Orange County": ["Anaheim", "Santa Ana", "Irvine", "Huntington Beach", "Garden Grove"],
            "Riverside County": ["Riverside", "Moreno Valley", "Corona", "Temecula", "Murrieta"],
            "San Bernardino County": ["San Bernardino", "Fontana", "Ontario", "Rancho Cucamonga"],
            "Santa Clara County": ["San Jose", "Sunnyvale", "Santa Clara", "Fremont", "Milpitas"],
            "Alameda County": ["Oakland", "Fremont", "Hayward", "Berkeley", "Union City"],
            "Sacramento County": ["Sacramento", "Elk Grove", "Citrus Heights", "Folsom"],
            "Contra Costa County": ["Concord", "Richmond", "Antioch", "Walnut Creek"],
            "San Francisco County": ["San Francisco"],
        }
    },
    "Colorado": {
        "code": "CO",
        "districts": {
            "Denver County": ["Denver"],
            "El Paso County": ["Colorado Springs", "Fountain", "Manitou Springs"],
            "Arapahoe County": ["Aurora", "Englewood", "Centennial", "Littleton"],
            "Jefferson County": ["Lakewood", "Arvada", "Westminster", "Golden"],
            "Adams County": ["Westminster", "Thornton", "Commerce City", "Brighton"],
            "Boulder County": ["Boulder", "Longmont", "Lafayette", "Louisville"],
            "Larimer County": ["Fort Collins", "Loveland", "Estes Park"],
            "Douglas County": ["Castle Rock", "Parker", "Lone Tree"],
        }
    },
    "Connecticut": {
        "code": "CT",
        "districts": {
            "Fairfield County": ["Bridgeport", "Stamford", "Norwalk", "Danbury", "Greenwich"],
            "Hartford County": ["Hartford", "New Britain", "West Hartford", "Bristol", "Meriden"],
            "New Haven County": ["New Haven", "Waterbury", "Hamden", "Milford", "West Haven"],
            "New London County": ["New London", "Norwich", "Groton", "Waterford"],
            "Middlesex County": ["Middletown", "Cromwell", "Middlefield"],
        }
    },
    "Delaware": {
        "code": "DE",
        "districts": {
            "New Castle County": ["Wilmington", "Newark", "Dover", "Middletown", "Smyrna"],
            "Kent County": ["Dover", "Milford", "Smyrna"],
            "Sussex County": ["Georgetown", "Seaford", "Rehoboth Beach", "Milford"],
        }
    },
    "District of Columbia": {
        "code": "DC",
        "districts": {
            "Washington DC": ["Washington", "Capitol Hill", "Georgetown", "Anacostia", "Dupont Circle"],
        }
    },
    "Florida": {
        "code": "FL",
        "districts": {
            "Miami-Dade County": ["Miami", "Hialeah", "Miami Gardens", "Miami Beach", "Coral Gables"],
            "Broward County": ["Fort Lauderdale", "Hollywood", "Pembroke Pines", "Miramar", "Coral Springs"],
            "Palm Beach County": ["West Palm Beach", "Boca Raton", "Boynton Beach", "Delray Beach"],
            "Hillsborough County": ["Tampa", "Brandon", "Plant City", "Temple Terrace"],
            "Orange County": ["Orlando", "Apopka", "Ocoee", "Winter Garden"],
            "Duval County": ["Jacksonville", "Jacksonville Beach", "Atlantic Beach"],
            "Pinellas County": ["St. Petersburg", "Clearwater", "Largo", "Tarpon Springs"],
            "Seminole County": ["Sanford", "Altamonte Springs", "Oviedo", "Casselberry"],
        }
    },
    "Georgia": {
        "code": "GA",
        "districts": {
            "Fulton County": ["Atlanta", "Alpharetta", "Roswell", "Sandy Springs", "Johns Creek"],
            "Gwinnett County": ["Lawrenceville", "Duluth", "Suwanee", "Norcross", "Buford"],
            "DeKalb County": ["Decatur", "Dunwoody", "Doraville", "Tucker"],
            "Cobb County": ["Marietta", "Smyrna", "Kennesaw", "Acworth"],
            "Chatham County": ["Savannah", "Pooler", "Garden City"],
            "Clayton County": ["Jonesboro", "Morrow", "Forest Park", "College Park"],
            "Cherokee County": ["Canton", "Woodstock", "Ball Ground"],
            "Hall County": ["Gainesville", "Oakwood", "Flowery Branch"],
        }
    },
    "Hawaii": {
        "code": "HI",
        "districts": {
            "Honolulu County": ["Honolulu", "Pearl City", "Hilo", "Kailua", "Waipahu"],
            "Hawaii County": ["Hilo", "Kailua-Kona", "Waimea"],
            "Maui County": ["Kahului", "Wailuku", "Lahaina", "Kihei"],
            "Kauai County": ["Lihue", "Kapaa", "Waimea"],
        }
    },
    "Idaho": {
        "code": "ID",
        "districts": {
            "Ada County": ["Boise", "Meridian", "Nampa", "Caldwell", "Garden City"],
            "Canyon County": ["Nampa", "Caldwell", "Middleton"],
            "Kootenai County": ["Coeur d'Alene", "Post Falls", "Hayden"],
            "Bannock County": ["Pocatello", "Chubbuck"],
            "Twin Falls County": ["Twin Falls", "Burley"],
        }
    },
    "Illinois": {
        "code": "IL",
        "districts": {
            "Cook County": ["Chicago", "Evanston", "Skokie", "Oak Park", "Cicero", "Schaumburg"],
            "DuPage County": ["Naperville", "Aurora", "Wheaton", "Downers Grove", "Elmhurst"],
            "Lake County": ["Waukegan", "North Chicago", "Zion", "Round Lake Beach"],
            "Will County": ["Joliet", "Bolingbrook", "Romeoville", "Plainfield"],
            "Kane County": ["Aurora", "Elgin", "Batavia", "Geneva", "St. Charles"],
            "Winnebago County": ["Rockford", "Loves Park", "Machesney Park"],
        }
    },
    "Indiana": {
        "code": "IN",
        "districts": {
            "Marion County": ["Indianapolis", "Lawrence", "Beech Grove", "Speedway"],
            "Hamilton County": ["Carmel", "Fishers", "Noblesville", "Westfield"],
            "Allen County": ["Fort Wayne", "New Haven"],
            "St. Joseph County": ["South Bend", "Mishawaka", "Granger"],
            "Vanderburgh County": ["Evansville", "Newburgh"],
            "Lake County": ["Gary", "Hammond", "Merrillville", "Munster"],
        }
    },
    "Iowa": {
        "code": "IA",
        "districts": {
            "Polk County": ["Des Moines", "West Des Moines", "Ankeny", "Urbandale", "Johnston"],
            "Linn County": ["Cedar Rapids", "Marion", "Hiawatha"],
            "Scott County": ["Davenport", "Bettendorf"],
            "Black Hawk County": ["Waterloo", "Cedar Falls"],
            "Johnson County": ["Iowa City", "Coralville", "North Liberty"],
        }
    },
    "Kansas": {
        "code": "KS",
        "districts": {
            "Johnson County": ["Overland Park", "Olathe", "Leawood", "Lenexa", "Shawnee"],
            "Sedgwick County": ["Wichita", "Derby", "Andover", "Haysville"],
            "Wyandotte County": ["Kansas City", "Bonner Springs"],
            "Douglas County": ["Lawrence", "Eudora"],
            "Shawnee County": ["Topeka", "Auburn"],
        }
    },
    "Kentucky": {
        "code": "KY",
        "districts": {
            "Jefferson County": ["Louisville", "St. Matthews", "Shively"],
            "Fayette County": ["Lexington", "Georgetown"],
            "Kenton County": ["Covington", "Florence", "Erlanger", "Independence"],
            "Boone County": ["Florence", "Burlington", "Union"],
            "Warren County": ["Bowling Green", "Smiths Grove"],
        }
    },
    "Louisiana": {
        "code": "LA",
        "districts": {
            "Orleans Parish": ["New Orleans", "Metairie", "Kenner"],
            "Jefferson Parish": ["Metairie", "Kenner", "Harvey", "Marrero"],
            "East Baton Rouge Parish": ["Baton Rouge", "Zachary", "Baker"],
            "St. Tammany Parish": ["Slidell", "Covington", "Mandeville"],
            "Caddo Parish": ["Shreveport", "Bossier City"],
        }
    },
    "Maine": {
        "code": "ME",
        "districts": {
            "Cumberland County": ["Portland", "South Portland", "Westbrook", "Scarborough"],
            "York County": ["Biddeford", "Saco", "Sanford", "Kennebunk"],
            "Penobscot County": ["Bangor", "Brewer", "Orono"],
            "Kennebec County": ["Augusta", "Waterville", "Winslow"],
        }
    },
    "Maryland": {
        "code": "MD",
        "districts": {
            "Montgomery County": ["Rockville", "Bethesda", "Gaithersburg", "Silver Spring", "Germantown"],
            "Prince George's County": ["College Park", "Bowie", "Greenbelt", "Hyattsville", "Laurel"],
            "Baltimore County": ["Towson", "Catonsville", "Essex", "Pikesville", "Randallstown"],
            "Anne Arundel County": ["Annapolis", "Glen Burnie", "Severn", "Crofton"],
            "Howard County": ["Columbia", "Ellicott City", "Laurel"],
            "Baltimore City": ["Baltimore"],
        }
    },
    "Massachusetts": {
        "code": "MA",
        "districts": {
            "Suffolk County": ["Boston", "Chelsea", "Revere", "Winthrop"],
            "Middlesex County": ["Cambridge", "Lowell", "Newton", "Somerville", "Quincy", "Malden"],
            "Worcester County": ["Worcester", "Framingham", "Marlborough", "Leominster"],
            "Essex County": ["Salem", "Lawrence", "Haverhill", "Methuen", "Lynn"],
            "Norfolk County": ["Quincy", "Braintree", "Weymouth", "Dedham", "Norwood"],
            "Plymouth County": ["Plymouth", "Brockton", "Bridgewater", "Marshfield"],
        }
    },
    "Michigan": {
        "code": "MI",
        "districts": {
            "Wayne County": ["Detroit", "Dearborn", "Warren", "Livonia", "Sterling Heights"],
            "Oakland County": ["Troy", "Pontiac", "Southfield", "Royal Oak", "Farmington Hills"],
            "Macomb County": ["Sterling Heights", "Warren", "Clinton Township", "St. Clair Shores"],
            "Kent County": ["Grand Rapids", "Wyoming", "Kentwood", "Walker"],
            "Washtenaw County": ["Ann Arbor", "Ypsilanti", "Saline"],
            "Ingham County": ["Lansing", "East Lansing", "Meridian Township"],
        }
    },
    "Minnesota": {
        "code": "MN",
        "districts": {
            "Hennepin County": ["Minneapolis", "Bloomington", "Plymouth", "Brooklyn Park", "Eden Prairie"],
            "Ramsey County": ["St. Paul", "Maplewood", "Roseville", "Shoreview"],
            "Dakota County": ["Apple Valley", "Burnsville", "Eagan", "Lakeville"],
            "Anoka County": ["Coon Rapids", "Blaine", "Andover", "Fridley"],
            "Washington County": ["Woodbury", "Stillwater", "Cottage Grove"],
            "St. Louis County": ["Duluth", "Hermantown", "Proctor"],
        }
    },
    "Mississippi": {
        "code": "MS",
        "districts": {
            "Hinds County": ["Jackson", "Clinton", "Raymond", "Terry"],
            "Harrison County": ["Biloxi", "Gulfport", "Long Beach"],
            "DeSoto County": ["Southaven", "Horn Lake", "Hernando", "Olive Branch"],
            "Rankin County": ["Flowood", "Richland", "Brandon", "Pearl"],
            "Madison County": ["Madison", "Ridgeland", "Canton"],
        }
    },
    "Missouri": {
        "code": "MO",
        "districts": {
            "St. Louis County": ["St. Louis", "Clayton", "Florissant", "Chesterfield", "Kirkwood"],
            "Jackson County": ["Kansas City", "Independence", "Lee's Summit", "Blue Springs"],
            "St. Charles County": ["St. Charles", "O'Fallon", "Wentzville", "St. Peters"],
            "Greene County": ["Springfield", "Republic", "Battlefield"],
            "Jefferson County": ["Arnold", "Festus", "Hillsboro"],
        }
    },
    "Montana": {
        "code": "MT",
        "districts": {
            "Yellowstone County": ["Billings", "Laurel", "Lockwood"],
            "Cascade County": ["Great Falls", "Black Eagle"],
            "Missoula County": ["Missoula", "East Missoula"],
            "Gallatin County": ["Bozeman", "Belgrade", "Manhattan"],
            "Lewis and Clark County": ["Helena", "East Helena"],
        }
    },
}

# Sample ZIP codes for major cities
SAMPLE_ZIPCODES = {
    "New York": [("10001", ["Midtown", "Chelsea"]), ("10002", ["Lower East Side"]), ("10003", ["East Village", "Greenwich Village"]), ("10004", ["Financial District"]), ("10007", ["Civic Center", "Tribeca"])],
    "Los Angeles": [("90001", ["Florence", "Florencia"]), ("90012", ["Little Tokyo", "Civic Center"]), ("90024", ["Westwood", "Bel Air"]), ("90210", ["Beverly Hills"]), ("90291", ["Venice"])],
    "Chicago": [("60601", ["The Loop", "Millennium Park"]), ("60602", ["The Loop"]), ("60614", ["Lincoln Park"]), ("60622", ["Wicker Park", "Bucktown"]), ("60657", ["Wrigleyville", "Lakeview"])],
    "Houston": [("77001", ["Downtown"]), ("77002", ["Midtown"]), ("77003", ["Third Ward"]), ("77004", ["Museum District"]), ("77019", ["River Oaks"])],
    "Phoenix": [("85001", ["Downtown"]), ("85004", ["Encanto"]), ("85016", ["Arcadia"]), ("85028", ["Paradise Valley"]), ("85254", ["Scottsdale"])],
    "Philadelphia": [("19101", ["Center City"]), ("19103", ["Rittenhouse Square"]), ("19104", ["University City"]), ("19106", ["Old City"]), ("19107", ["Washington Square West"])],
    "San Antonio": [("78201", ["Woodlawn"]), ("78205", ["Downtown"]), ("78209", ["Alamo Heights"]), ("78216", ["Airport"]), ("78232", ["Stone Oak"])],
    "San Diego": [("92101", ["Downtown", "Little Italy"]), ("92103", ["Mission Hills", "Hillcrest"]), ("92108", ["Mission Valley"]), ("92121", ["Sorrento Valley"]), ("92130", ["Carmel Valley"])],
    "Dallas": [("75201", ["Downtown"]), ("75205", ["Park Cities"]), ("75206", ["Lower Greenville"]), ("75219", ["Oak Lawn"]), ("75225", ["Preston Hollow"])],
    "San Jose": [("95101", ["Downtown"]), ("95110", ["West San Jose"]), ("95112", ["Downtown"]), ("95128", ["Rose Garden"]), ("95129", ["West San Jose"])],
    "Austin": [("78701", ["Downtown"]), ("78702", ["East Austin"]), ("78703", ["Tarrytown"]), ("78704", ["Travis Heights"]), ("78745", ["South Congress"])],
    "Jacksonville": [("32099", ["Downtown"]), ("32202", ["Downtown"]), ("32205", ["Avondale", "Riverside"]), ("32207", ["San Marco"]), ("32217", ["Mandarin"])],
    "Fort Worth": [("76101", ["Downtown"]), ("76102", ["Downtown"]), ("76104", ["Near Southside"]), ("76107", ["Cultural District"]), ("76109", ["TCU Area"])],
    "Columbus": [("43085", ["Worthington"]), ("43201", ["Short North"]), ("43202", ["Clintonville"]), ("43210", ["University District"]), ("43215", ["Downtown"])],
    "Indianapolis": [("46201", ["Near Eastside"]), ("46202", ["Herron-Morton Place"]), ("46203", ["Bates-Hendricks"]), ("46204", ["Downtown"]), ("46220", ["Broad Ripple"])],
    "Charlotte": [("28201", ["Downtown"]), ("28202", ["Uptown"]), ("28203", ["South End"]), ("28204", ["Dilworth"]), ("28205", ["Plaza Midwood"])],
    "San Francisco": [("94101", ["SoMa"]), ("94102", ["Tenderloin"]), ("94103", ["SoMa"]), ("94107", ["Potrero Hill"]), ("94110", ["Mission District"])],
    "Seattle": [("98101", ["Downtown"]), ("98102", ["Capitol Hill"]), ("98103", ["Fremont", "Wallingford"]), ("98104", ["Pioneer Square"]), ("98122", ["Capitol Hill", "Madison Valley"])],
    "Denver": [("80201", ["Downtown"]), ("80202", ["Downtown", "LoDo"]), ("80203", ["Capitol Hill"]), ("80204", ["West Colfax"]), ("80205", ["Five Points"])],
    "Nashville": [("37201", ["Downtown"]), ("37203", ["Gulch", "Medical Center"]), ("37204", ["Berry Hill"]), ("37205", ["Belle Meade"]), ("37206", ["East Nashville"])],
    "Oklahoma City": [("73101", ["Downtown"]), ("73102", ["Downtown"]), ("73103", ["Heritage Hills"]), ("73104", ["Bricktown"]), ("73105", ["Lincoln Terrace"])],
    "Atlanta": [("30301", ["Downtown"]), ("30303", ["Downtown"]), ("30305", ["Buckhead"]), ("30306", ["Virginia-Highland"]), ("30307", ["Inman Park"])],
    "Miami": [("33101", ["Little Haiti"]), ("33125", ["Little Havana"]), ("33130", ["Brickell"]), ("33131", ["Downtown"]), ("33132", ["Biscayne Bay"])],
    "Boston": [("02101", ["Downtown"]), ("02108", ["Beacon Hill"]), ("02109", ["North End"]), ("02110", ["Financial District"]), ("02116", ["Back Bay"])],
    "Portland": [("97201", ["SW Portland"]), ("97202", ["SE Portland"]), ("97203", ["St. Johns"]), ("97204", ["Downtown"]), ("97205", ["Northwest"])],
    "Las Vegas": [("89101", ["Downtown"]), ("89102", ["The Strip"]), ("89103", ["Spring Valley"]), ("89109", ["Las Vegas Strip"]), ("89119", ["Paradise"])],
    "Memphis": [("38101", ["Downtown"]), ("38103", ["Downtown"]), ("38104", ["Midtown"]), ("38105", ["Medical Center"]), ("38111", ["East Memphis"])],
    "Louisville": [("40201", ["West End"]), ("40202", ["Downtown"]), ("40203", ["Old Louisville"]), ("40205", ["Highlands"]), ("40206", ["Crescent Hill"])],
    "Baltimore": [("21201", ["Downtown"]), ("21202", ["Inner Harbor"]), ("21210", ["Roland Park"]), ("21211", ["Hampden"]), ("21218", ["Waverly", "Clifton Park"])],
    "Milwaukee": [("53201", ["East Side"]), ("53202", ["East Side"]), ("53203", ["Downtown"]), ("53204", ["Walker's Point"]), ("53205", ["Harambee"])],
}

# ============================================================
# Remaining States: Nebraska → Wyoming
# ============================================================
USA_DATA.update({
    "Nebraska": {
        "code": "NE",
        "districts": {
            "Douglas County": ["Omaha", "Ralston", "Bennington"],
            "Lancaster County": ["Lincoln", "Waverly", "Malcolm"],
            "Sarpy County": ["Bellevue", "Papillion", "La Vista", "Gretna"],
            "Hall County": ["Grand Island", "Wood River"],
            "Buffalo County": ["Kearney", "Gibbon"],
        }
    },
    "Nevada": {
        "code": "NV",
        "districts": {
            "Clark County": ["Las Vegas", "Henderson", "North Las Vegas", "Enterprise", "Summerlin"],
            "Washoe County": ["Reno", "Sparks", "Sun Valley"],
            "Carson City": ["Carson City"],
            "Elko County": ["Elko", "Spring Creek"],
        }
    },
    "New Hampshire": {
        "code": "NH",
        "districts": {
            "Hillsborough County": ["Manchester", "Nashua", "Milford", "Merrimack"],
            "Rockingham County": ["Derry", "Salem", "Londonderry", "Portsmouth"],
            "Merrimack County": ["Concord", "Penacook", "Bow"],
            "Strafford County": ["Dover", "Rochester", "Durham"],
        }
    },
    "New Jersey": {
        "code": "NJ",
        "districts": {
            "Bergen County": ["Hackensack", "Fort Lee", "Paramus", "Teaneck", "Englewood"],
            "Essex County": ["Newark", "East Orange", "Irvington", "West Orange", "Montclair"],
            "Middlesex County": ["New Brunswick", "Edison", "Woodbridge", "Piscataway"],
            "Hudson County": ["Jersey City", "Bayonne", "Union City", "West New York"],
            "Passaic County": ["Paterson", "Clifton", "Passaic", "Wayne"],
            "Union County": ["Elizabeth", "Plainfield", "Linden", "Westfield"],
            "Monmouth County": ["Neptune", "Red Bank", "Long Branch", "Freehold"],
            "Ocean County": ["Toms River", "Lakewood", "Brick"],
        }
    },
    "New Mexico": {
        "code": "NM",
        "districts": {
            "Bernalillo County": ["Albuquerque", "Rio Rancho", "Corrales"],
            "Dona Ana County": ["Las Cruces", "Sunland Park", "Mesilla"],
            "Santa Fe County": ["Santa Fe", "Espanola"],
            "Sandoval County": ["Rio Rancho", "Bernalillo", "Placitas"],
        }
    },
    "New York": {
        "code": "NY",
        "districts": {
            "New York County": ["New York City", "Manhattan", "Harlem", "Upper East Side"],
            "Kings County": ["Brooklyn", "Flatbush", "Bay Ridge", "Williamsburg"],
            "Queens County": ["Queens", "Flushing", "Jamaica", "Astoria", "Forest Hills"],
            "Bronx County": ["Bronx", "Yonkers", "Mount Vernon"],
            "Richmond County": ["Staten Island", "St. George"],
            "Erie County": ["Buffalo", "Cheektowaga", "Amherst", "Tonawanda"],
            "Monroe County": ["Rochester", "Irondequoit", "Greece", "Gates"],
            "Onondaga County": ["Syracuse", "Salina", "Geddes"],
            "Albany County": ["Albany", "Colonie", "Cohoes", "Watervliet"],
            "Westchester County": ["Yonkers", "New Rochelle", "Mount Vernon", "White Plains"],
        }
    },
    "North Carolina": {
        "code": "NC",
        "districts": {
            "Mecklenburg County": ["Charlotte", "Mint Hill", "Matthews", "Pineville"],
            "Wake County": ["Raleigh", "Cary", "Apex", "Morrisville"],
            "Guilford County": ["Greensboro", "High Point", "Jamestown"],
            "Forsyth County": ["Winston-Salem", "Kernersville", "Lewisville"],
            "Durham County": ["Durham", "Research Triangle Park"],
            "Cumberland County": ["Fayetteville", "Hope Mills", "Spring Lake"],
            "Buncombe County": ["Asheville", "Woodfin", "Weaverville"],
        }
    },
    "North Dakota": {
        "code": "ND",
        "districts": {
            "Cass County": ["Fargo", "West Fargo", "Moorhead"],
            "Burleigh County": ["Bismarck", "Lincoln"],
            "Grand Forks County": ["Grand Forks", "East Grand Forks"],
            "Ward County": ["Minot", "Burlington"],
        }
    },
    "Ohio": {
        "code": "OH",
        "districts": {
            "Franklin County": ["Columbus", "Dublin", "Westerville", "Hilliard", "Grove City"],
            "Cuyahoga County": ["Cleveland", "Parma", "Lakewood", "Euclid", "Cleveland Heights"],
            "Hamilton County": ["Cincinnati", "Blue Ash", "Norwood", "Forest Park"],
            "Summit County": ["Akron", "Cuyahoga Falls", "Fairlawn"],
            "Montgomery County": ["Dayton", "Kettering", "Huber Heights", "Fairborn"],
            "Lucas County": ["Toledo", "Maumee", "Oregon", "Sylvania"],
        }
    },
    "Oklahoma": {
        "code": "OK",
        "districts": {
            "Oklahoma County": ["Oklahoma City", "Edmond", "Midwest City", "Del City"],
            "Tulsa County": ["Tulsa", "Broken Arrow", "Jenks", "Bixby"],
            "Cleveland County": ["Norman", "Moore", "Midwest City"],
            "Canadian County": ["Yukon", "Mustang", "El Reno"],
        }
    },
    "Oregon": {
        "code": "OR",
        "districts": {
            "Multnomah County": ["Portland", "Gresham", "Troutdale"],
            "Washington County": ["Hillsboro", "Beaverton", "Tigard", "Tualatin"],
            "Clackamas County": ["Oregon City", "Lake Oswego", "West Linn", "Happy Valley"],
            "Lane County": ["Eugene", "Springfield", "Florence"],
            "Marion County": ["Salem", "Keizer", "Woodburn"],
            "Jackson County": ["Medford", "Ashland", "Central Point"],
        }
    },
    "Pennsylvania": {
        "code": "PA",
        "districts": {
            "Philadelphia County": ["Philadelphia", "Germantown", "Manayunk"],
            "Allegheny County": ["Pittsburgh", "McKeesport", "Bethel Park", "Monroeville"],
            "Montgomery County": ["Norristown", "King of Prussia", "Lansdale", "Abington"],
            "Bucks County": ["Levittown", "Bristol", "Doylestown", "Newtown"],
            "Delaware County": ["Chester", "Upper Darby", "Haverford", "Radnor"],
            "Lancaster County": ["Lancaster", "Manheim", "Elizabethtown"],
            "York County": ["York", "Spring Garden", "West York"],
        }
    },
    "Rhode Island": {
        "code": "RI",
        "districts": {
            "Providence County": ["Providence", "Woonsocket", "Pawtucket", "North Providence"],
            "Kent County": ["Warwick", "Coventry", "West Warwick"],
            "Washington County": ["South Kingstown", "Narragansett", "Westerly"],
            "Newport County": ["Newport", "Middletown", "Portsmouth"],
        }
    },
    "South Carolina": {
        "code": "SC",
        "districts": {
            "Greenville County": ["Greenville", "Mauldin", "Simpsonville", "Greer"],
            "Richland County": ["Columbia", "Forest Acres", "Irmo"],
            "Charleston County": ["Charleston", "North Charleston", "Mount Pleasant", "Summerville"],
            "Horry County": ["Myrtle Beach", "Conway", "Socastee"],
            "Lexington County": ["Lexington", "Irmo", "Cayce", "West Columbia"],
        }
    },
    "South Dakota": {
        "code": "SD",
        "districts": {
            "Minnehaha County": ["Sioux Falls", "Brandon", "Harrisburg"],
            "Pennington County": ["Rapid City", "Box Elder", "Summerset"],
            "Lincoln County": ["Harrisburg", "Tea", "Canton"],
            "Brown County": ["Aberdeen", "Bath"],
        }
    },
    "Tennessee": {
        "code": "TN",
        "districts": {
            "Shelby County": ["Memphis", "Bartlett", "Germantown", "Collierville"],
            "Davidson County": ["Nashville", "Belle Meade", "Forest Hills"],
            "Knox County": ["Knoxville", "Powell", "Farragut"],
            "Hamilton County": ["Chattanooga", "East Ridge", "Red Bank"],
            "Rutherford County": ["Murfreesboro", "Smyrna", "LaVergne"],
            "Williamson County": ["Franklin", "Brentwood", "Nolensville"],
        }
    },
    "Texas": {
        "code": "TX",
        "districts": {
            "Harris County": ["Houston", "Pasadena", "Pearland", "League City", "Sugar Land"],
            "Dallas County": ["Dallas", "Irving", "Garland", "Mesquite", "Richardson"],
            "Tarrant County": ["Fort Worth", "Arlington", "Grand Prairie", "Mansfield"],
            "Bexar County": ["San Antonio", "Converse", "Universal City", "Leon Valley"],
            "Travis County": ["Austin", "Pflugerville", "Round Rock", "Cedar Park"],
            "Collin County": ["Plano", "McKinney", "Frisco", "Allen", "Richardson"],
            "Hidalgo County": ["McAllen", "Edinburg", "Mission", "Pharr"],
            "El Paso County": ["El Paso", "Socorro", "Horizon City"],
            "Williamson County": ["Round Rock", "Georgetown", "Cedar Park", "Leander"],
        }
    },
    "Utah": {
        "code": "UT",
        "districts": {
            "Salt Lake County": ["Salt Lake City", "West Valley City", "Sandy", "West Jordan", "Murray"],
            "Utah County": ["Provo", "Orem", "Lehi", "American Fork", "Springville"],
            "Davis County": ["Layton", "Bountiful", "Kaysville", "Clearfield"],
            "Weber County": ["Ogden", "Roy", "Riverdale", "South Ogden"],
            "Washington County": ["St. George", "Washington", "Ivins"],
        }
    },
    "Vermont": {
        "code": "VT",
        "districts": {
            "Chittenden County": ["Burlington", "South Burlington", "Winooski", "Williston"],
            "Rutland County": ["Rutland", "Killington"],
            "Washington County": ["Montpelier", "Barre"],
            "Addison County": ["Middlebury", "Bristol"],
        }
    },
    "Virginia": {
        "code": "VA",
        "districts": {
            "Fairfax County": ["Fairfax", "Reston", "Herndon", "Springfield", "McLean"],
            "Prince William County": ["Manassas", "Woodbridge", "Dale City", "Lake Ridge"],
            "Loudoun County": ["Leesburg", "Ashburn", "Sterling", "South Riding"],
            "Virginia Beach City": ["Virginia Beach", "Chesapeake", "Norfolk"],
            "Chesterfield County": ["Chester", "Midlothian", "Colonial Heights"],
            "Henrico County": ["Richmond", "Short Pump", "Glen Allen"],
            "Arlington County": ["Arlington", "Clarendon", "Rosslyn"],
        }
    },
    "Washington": {
        "code": "WA",
        "districts": {
            "King County": ["Seattle", "Bellevue", "Renton", "Kent", "Kirkland", "Redmond"],
            "Pierce County": ["Tacoma", "Lakewood", "Puyallup", "Bonney Lake"],
            "Snohomish County": ["Everett", "Lynnwood", "Marysville", "Edmonds"],
            "Spokane County": ["Spokane", "Spokane Valley", "Cheney"],
            "Clark County": ["Vancouver", "Camas", "Washougal", "Battle Ground"],
            "Thurston County": ["Olympia", "Lacey", "Tumwater"],
        }
    },
    "West Virginia": {
        "code": "WV",
        "districts": {
            "Kanawha County": ["Charleston", "South Charleston", "St. Albans"],
            "Cabell County": ["Huntington", "Barboursville"],
            "Monongalia County": ["Morgantown", "Star City"],
            "Berkeley County": ["Martinsburg", "Hedgesville"],
        }
    },
    "Wisconsin": {
        "code": "WI",
        "districts": {
            "Milwaukee County": ["Milwaukee", "Wauwatosa", "West Allis", "Greenfield"],
            "Dane County": ["Madison", "Fitchburg", "Sun Prairie", "Middleton"],
            "Waukesha County": ["Waukesha", "Pewaukee", "Brookfield", "Muskego"],
            "Brown County": ["Green Bay", "De Pere", "Bellevue"],
            "Racine County": ["Racine", "Mount Pleasant", "Caledonia"],
        }
    },
    "Wyoming": {
        "code": "WY",
        "districts": {
            "Laramie County": ["Cheyenne", "Burns", "Albin"],
            "Natrona County": ["Casper", "Mills", "Evansville"],
            "Fremont County": ["Riverton", "Lander", "Dubois"],
            "Albany County": ["Laramie", "Rock River"],
        }
    },
})


class Command(BaseCommand):
    help = 'Seed USA address master data (States, Counties, Cities, ZIP Codes)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing USA location data before seeding',
        )

    def handle(self, *args, **options):
        from location_master.models import Country, State, District, City, Pincode, Area

        start = time.time()

        if options['clear']:
            self.stdout.write('Clearing existing USA location data...')
            try:
                usa = Country.objects.get(code='US')
                Area.objects.filter(pincode__city__district__state__country=usa).delete()
                Pincode.objects.filter(city__district__state__country=usa).delete()
                City.objects.filter(district__state__country=usa).delete()
                District.objects.filter(state__country=usa).delete()
                State.objects.filter(country=usa).delete()
                usa.delete()
                self.stdout.write(self.style.WARNING('Cleared all USA location data.'))
            except Country.DoesNotExist:
                self.stdout.write('No existing USA data to clear.')

        self.stdout.write('Creating Country: United States...')
        usa, _ = Country.objects.get_or_create(
            code='US',
            defaults={'name': 'United States'}
        )

        new_states = new_counties = new_cities = 0

        with transaction.atomic():
            for state_name, state_info in USA_DATA.items():
                state, created = State.objects.get_or_create(
                    country=usa,
                    name=state_name,
                    defaults={'code': state_info['code']}
                )
                if created:
                    new_states += 1
                    self.stdout.write(f'  + State: {state_name} ({state_info["code"]})')

                for county_name, cities in state_info['districts'].items():
                    district, created = District.objects.get_or_create(
                        state=state,
                        name=county_name,
                    )
                    if created:
                        new_counties += 1

                    for city_name in cities:
                        _, created = City.objects.get_or_create(
                            district=district,
                            name=city_name,
                        )
                        if created:
                            new_cities += 1

        # Show both newly created AND total in DB
        db_states = State.objects.filter(country=usa).count()
        db_counties = District.objects.filter(state__country=usa).count()
        db_cities = City.objects.filter(district__state__country=usa).count()

        if new_states == 0 and db_states > 0:
            self.stdout.write(self.style.WARNING(
                f'[INFO] Data already exists — no new records created.'
            ))
        self.stdout.write(self.style.SUCCESS(
            f'[OK] Newly created : {new_states} states, {new_counties} counties, {new_cities} cities'
        ))
        self.stdout.write(self.style.SUCCESS(
            f'[OK] Total in DB   : {db_states} states, {db_counties} counties, {db_cities} cities'
        ))

        # Seed ZIP codes and areas for major cities
        new_zipcodes = new_areas = 0
        with transaction.atomic():
            for city_name, zipcodes in SAMPLE_ZIPCODES.items():
                city_qs = City.objects.filter(name=city_name)
                if not city_qs.exists():
                    continue
                city_obj = city_qs.first()
                for zipcode_code, areas in zipcodes:
                    pincode, created = Pincode.objects.get_or_create(
                        city=city_obj, code=zipcode_code
                    )
                    if created:
                        new_zipcodes += 1
                    for area_name in areas:
                        _, created = Area.objects.get_or_create(
                            pincode=pincode, name=area_name
                        )
                        if created:
                            new_areas += 1

        db_zipcodes = Pincode.objects.filter(city__district__state__country=usa).count()
        db_areas = Area.objects.filter(pincode__city__district__state__country=usa).count()

        elapsed = round(time.time() - start, 2)
        self.stdout.write(self.style.SUCCESS(
            f'[OK] ZIP codes — new: {new_zipcodes}, total in DB: {db_zipcodes}'
        ))
        self.stdout.write(self.style.SUCCESS(
            f'[OK] Areas     — new: {new_areas}, total in DB: {db_areas}'
        ))
        self.stdout.write(self.style.SUCCESS(f'[DONE] USA address data seeding complete! ({elapsed}s)'))

