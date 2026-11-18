"""Place names in posting locations and in searches, for the "in X, not Y" mismatch tag (11-06).

parse() turns a location string into the most specific places it names, each a path (country, region, city) cut
where unknown: '杭州, 浙江' -> [('China', 'Zhejiang', 'Hangzhou')], '浙江' -> [('China', 'Zhejiang')],
'Remote (Europe)' -> one path per European country. Two places fit when one path is a prefix of the other, so
'浙江' fits a search for Hangzhou (it may be there) and '山东' does not. A string with no known place, or one that
says anywhere / worldwide, gives [] and is never tagged: the tag is only for postings that clearly break the place.
The list covers the places in the corpus and the evaluation queries, not the world.

Since 11-07 the same parse also classifies every posting by place (classify(), stored in opp_places by regions.py),
for the region filter and the region listing; CONTINENTS gives the top level.
"""
import re

COUNTRIES = {
    'China': ['china', 'mainland china', 'prc', '中国', '中國', '大陆'], 'Taiwan': ['taiwan', '台湾', '台灣', '臺灣'],
    'Hong Kong': ['hong kong', '香港'], 'Japan': ['japan', '日本'], 'South Korea': ['south korea', 'korea', '韩国'],
    'Singapore': ['singapore', '新加坡'], 'Malaysia': ['malaysia'], 'Indonesia': ['indonesia'], 'Vietnam': ['vietnam'],
    'Thailand': ['thailand'], 'Philippines': ['philippines'], 'India': ['india'], 'Pakistan': ['pakistan'],
    'Sri Lanka': ['sri lanka'], 'United States': ['united states', 'usa', 'u.s.', 'america', '美国'],
    'Canada': ['canada', '加拿大'], 'Mexico': ['mexico'], 'Brazil': ['brazil', 'brasil'], 'Argentina': ['argentina'],
    'Colombia': ['colombia'], 'Chile': ['chile'], 'Peru': ['peru'], 'Costa Rica': ['costa rica'],
    'United Kingdom': ['united kingdom', 'england', 'scotland', 'wales', 'great britain', 'britain', '英国'],
    'Ireland': ['ireland', '爱尔兰'], 'Germany': ['germany', 'deutschland', '德国'], 'France': ['france', '法国'],
    'Netherlands': ['netherlands', 'nederland', 'holland'], 'Belgium': ['belgium'], 'Luxembourg': ['luxembourg'],
    'Spain': ['spain', 'españa'], 'Portugal': ['portugal'], 'Italy': ['italy'], 'Switzerland': ['switzerland'],
    'Austria': ['austria'], 'Poland': ['poland'], 'Czechia': ['czechia', 'czech republic'], 'Hungary': ['hungary'],
    'Romania': ['romania'], 'Bulgaria': ['bulgaria'], 'Serbia': ['serbia'], 'Greece': ['greece'],
    'Ukraine': ['ukraine'], 'Lithuania': ['lithuania'], 'Estonia': ['estonia'], 'Latvia': ['latvia'],
    'Sweden': ['sweden'], 'Norway': ['norway'], 'Denmark': ['denmark'], 'Finland': ['finland'],
    'Turkey': ['turkey', 'türkiye'], 'Israel': ['israel'], 'United Arab Emirates': ['united arab emirates', 'uae'],
    'Qatar': ['qatar'], 'Saudi Arabia': ['saudi arabia'], 'Egypt': ['egypt'], 'Nigeria': ['nigeria'],
    'Kenya': ['kenya'], 'South Africa': ['south africa'], 'Australia': ['australia', '澳大利亚', '澳洲'],
    'New Zealand': ['new zealand', '新西兰'],
    # 11-07: named in postings the list above missed. Georgia is left out: the US state is far more common
    'Croatia': ['croatia', 'hrvatska'], 'Slovenia': ['slovenia'], 'Slovakia': ['slovakia'], 'Cyprus': ['cyprus'],
    'Malta': ['malta'], 'Iceland': ['iceland'], 'Bosnia and Herzegovina': ['bosnia and herzegovina', 'bosnia'],
    'North Macedonia': ['north macedonia', 'macedonia'], 'Albania': ['albania'], 'Montenegro': ['montenegro'],
    'Moldova': ['moldova'], 'Armenia': ['armenia'], 'Azerbaijan': ['azerbaijan'], 'Kazakhstan': ['kazakhstan'],
    'Lebanon': ['lebanon'], 'Jordan': ['jordan'], 'Kuwait': ['kuwait'], 'Bahrain': ['bahrain'], 'Oman': ['oman'],
    'Morocco': ['morocco'], 'Tunisia': ['tunisia'], 'Ghana': ['ghana'], 'Ethiopia': ['ethiopia'], 'Uganda': ['uganda'],
    'Rwanda': ['rwanda'], 'Tanzania': ['tanzania'], 'Bangladesh': ['bangladesh'], 'Nepal': ['nepal'],
    'Cambodia': ['cambodia'], 'Guatemala': ['guatemala'], 'Honduras': ['honduras'], 'El Salvador': ['el salvador'],
    'Nicaragua': ['nicaragua'], 'Panama': ['panama'], 'Dominican Republic': ['dominican republic'],
    'Puerto Rico': ['puerto rico'], 'Jamaica': ['jamaica'], 'Trinidad and Tobago': ['trinidad and tobago', 'trinidad'],
    'Barbados': ['barbados'], 'Bahamas': ['bahamas'], 'Cuba': ['cuba'], 'Haiti': ['haiti'], 'Uruguay': ['uruguay'],
    'Paraguay': ['paraguay'], 'Ecuador': ['ecuador'], 'Bolivia': ['bolivia'], 'Venezuela': ['venezuela'],
}
for _c, _al in (('China', ['全国']), ('Switzerland', ['schweiz', 'suisse', 'svizzera', '瑞士']),
                ('France', ['frankreich', 'frankrijk']), ('Austria', ['österreich', '奥地利']),
                ('Italy', ['italia', '意大利']), ('Poland', ['polska']), ('Netherlands', ['荷兰']),
                ('Spain', ['西班牙']), ('Singapore', ['狮城']), ('Japan', ['日本国'])):
    COUNTRIES[_c] = COUNTRIES[_c] + _al  # 全国 in a Chinese posting means anywhere in China
# ISO 3166 codes. Only trusted where the source puts one in a fixed place (SmartRecruiters ends every location with
# it); free text keeps the shorter CODES list, since IN / DE / IT / AR are also words or US states.
ISO2 = {'CN': 'China', 'TW': 'Taiwan', 'HK': 'Hong Kong', 'JP': 'Japan', 'KR': 'South Korea', 'SG': 'Singapore',
        'MY': 'Malaysia', 'ID': 'Indonesia', 'VN': 'Vietnam', 'TH': 'Thailand', 'PH': 'Philippines', 'IN': 'India',
        'PK': 'Pakistan', 'LK': 'Sri Lanka', 'US': 'United States', 'CA': 'Canada', 'MX': 'Mexico', 'BR': 'Brazil',
        'AR': 'Argentina', 'CO': 'Colombia', 'CL': 'Chile', 'PE': 'Peru', 'CR': 'Costa Rica', 'GB': 'United Kingdom',
        'UK': 'United Kingdom', 'IE': 'Ireland', 'DE': 'Germany', 'FR': 'France', 'NL': 'Netherlands', 'BE': 'Belgium',
        'LU': 'Luxembourg', 'ES': 'Spain', 'PT': 'Portugal', 'IT': 'Italy', 'CH': 'Switzerland', 'AT': 'Austria',
        'PL': 'Poland', 'CZ': 'Czechia', 'HU': 'Hungary', 'RO': 'Romania', 'BG': 'Bulgaria', 'RS': 'Serbia',
        'GR': 'Greece', 'UA': 'Ukraine', 'LT': 'Lithuania', 'EE': 'Estonia', 'LV': 'Latvia', 'SE': 'Sweden',
        'NO': 'Norway', 'DK': 'Denmark', 'FI': 'Finland', 'TR': 'Turkey', 'IL': 'Israel', 'AE': 'United Arab Emirates',
        'QA': 'Qatar', 'SA': 'Saudi Arabia', 'EG': 'Egypt', 'NG': 'Nigeria', 'KE': 'Kenya', 'ZA': 'South Africa',
        'AU': 'Australia', 'NZ': 'New Zealand', 'HR': 'Croatia', 'SI': 'Slovenia', 'SK': 'Slovakia', 'CY': 'Cyprus',
        'MT': 'Malta', 'IS': 'Iceland', 'BA': 'Bosnia and Herzegovina', 'MK': 'North Macedonia', 'AL': 'Albania',
        'ME': 'Montenegro', 'MD': 'Moldova', 'AM': 'Armenia', 'AZ': 'Azerbaijan', 'KZ': 'Kazakhstan', 'LB': 'Lebanon',
        'JO': 'Jordan', 'KW': 'Kuwait', 'BH': 'Bahrain', 'OM': 'Oman', 'MA': 'Morocco', 'TN': 'Tunisia', 'GH': 'Ghana',
        'ET': 'Ethiopia', 'UG': 'Uganda', 'RW': 'Rwanda', 'TZ': 'Tanzania', 'BD': 'Bangladesh', 'NP': 'Nepal',
        'KH': 'Cambodia', 'GT': 'Guatemala', 'HN': 'Honduras', 'SV': 'El Salvador', 'NI': 'Nicaragua', 'PA': 'Panama',
        'DO': 'Dominican Republic', 'PR': 'Puerto Rico', 'JM': 'Jamaica', 'TT': 'Trinidad and Tobago', 'BB': 'Barbados',
        'BS': 'Bahamas', 'CU': 'Cuba', 'HT': 'Haiti', 'UY': 'Uruguay', 'PY': 'Paraguay', 'EC': 'Ecuador', 'BO': 'Bolivia',
        'VE': 'Venezuela'}
CODES = {'US': 'United States', 'USA': 'United States', 'UK': 'United Kingdom', 'GB': 'United Kingdom',
         'CN': 'China', 'FR': 'France', 'BR': 'Brazil', 'MY': 'Malaysia', 'PH': 'Philippines', 'SG': 'Singapore',
         'AU': 'Australia', 'NZ': 'New Zealand', 'IE': 'Ireland', 'NL': 'Netherlands', 'ES': 'Spain', 'PT': 'Portugal',
         'PL': 'Poland', 'SE': 'Sweden', 'CH': 'Switzerland', 'JP': 'Japan', 'KR': 'South Korea', 'MX': 'Mexico',
         'CL': 'Chile', 'PE': 'Peru', 'BG': 'Bulgaria', 'RO': 'Romania'}  # IN, DE, IT, AR left out: US states / words
US_STATES = {'CA': 'california', 'NY': 'new york state', 'TX': 'texas', 'WA': 'washington state', 'MA': 'massachusetts',
             'IL': 'illinois', 'CO': 'colorado', 'PA': 'pennsylvania', 'AZ': 'arizona', 'OR': 'oregon', 'GA': None,
             'FL': 'florida', 'NC': 'north carolina', 'VA': 'virginia', 'NJ': 'new jersey', 'MI': 'michigan',
             'MN': 'minnesota', 'UT': 'utah', 'OH': 'ohio', 'TN': 'tennessee', 'MD': 'maryland', 'DC': None,
             'CT': 'connecticut', 'NV': 'nevada', 'MO': 'missouri', 'WI': 'wisconsin', 'NM': 'new mexico'}
CA_PROVINCES = {'ON': 'ontario', 'BC': 'british columbia', 'QC': 'quebec', 'AB': 'alberta', 'NS': 'nova scotia'}
CN_PROVINCES = {'Zhejiang': '浙江', 'Jiangsu': '江苏', 'Guangdong': '广东', 'Sichuan': '四川', 'Hubei': '湖北',
                'Shaanxi': '陕西', 'Shandong': '山东', 'Hunan': '湖南', 'Henan': '河南', 'Anhui': '安徽', 'Fujian': '福建',
                'Liaoning': '辽宁', 'Yunnan': '云南', 'Hebei': '河北', 'Shanxi': '山西', 'Jiangxi': '江西', 'Guangxi': '广西',
                'Guizhou': '贵州', 'Jilin': '吉林', 'Heilongjiang': '黑龙江', 'Gansu': '甘肃', 'Hainan': '海南',
                'Inner Mongolia': '内蒙古', 'Xinjiang': '新疆'}
# city: (country, region or None, aliases). A metro area counts as one city.
CITIES = {
    'Beijing': ('China', 'Beijing', ['beijing', '北京']), 'Shanghai': ('China', 'Shanghai', ['shanghai', '上海']),
    'Tianjin': ('China', 'Tianjin', ['tianjin', '天津']), 'Chongqing': ('China', 'Chongqing', ['chongqing', '重庆']),
    'Guangzhou': ('China', 'Guangdong', ['guangzhou', '广州']), 'Shenzhen': ('China', 'Guangdong', ['shenzhen', '深圳']),
    'Dongguan': ('China', 'Guangdong', ['dongguan', '东莞']), 'Foshan': ('China', 'Guangdong', ['foshan', '佛山']),
    'Hangzhou': ('China', 'Zhejiang', ['hangzhou', '杭州']), 'Ningbo': ('China', 'Zhejiang', ['ningbo', '宁波']),
    'Nanjing': ('China', 'Jiangsu', ['nanjing', '南京']), 'Suzhou': ('China', 'Jiangsu', ['suzhou', '苏州']),
    'Wuxi': ('China', 'Jiangsu', ['wuxi', '无锡']), 'Chengdu': ('China', 'Sichuan', ['chengdu', '成都']),
    'Wuhan': ('China', 'Hubei', ['wuhan', '武汉']), "Xi'an": ('China', 'Shaanxi', ["xi'an", 'xian', '西安']),
    'Qingdao': ('China', 'Shandong', ['qingdao', '青岛']), 'Jinan': ('China', 'Shandong', ['jinan', '济南']),
    'Changsha': ('China', 'Hunan', ['changsha', '长沙']), 'Zhengzhou': ('China', 'Henan', ['zhengzhou', '郑州']),
    'Hefei': ('China', 'Anhui', ['hefei', '合肥']), 'Xiamen': ('China', 'Fujian', ['xiamen', '厦门']),
    'Fuzhou': ('China', 'Fujian', ['fuzhou', '福州']), 'Dalian': ('China', 'Liaoning', ['dalian', '大连']),
    'Shenyang': ('China', 'Liaoning', ['shenyang', '沈阳']), 'Kunming': ('China', 'Yunnan', ['kunming', '昆明']),
    'Taipei': ('Taiwan', None, ['taipei', 'new taipei', '台北', '臺北', '新北']),
    'Taoyuan': ('Taiwan', None, ['taoyuan', '桃园', '桃園']), 'Taichung': ('Taiwan', None, ['taichung', '台中', '臺中']),
    'Tainan': ('Taiwan', None, ['tainan', '台南', '臺南']), 'Kaohsiung': ('Taiwan', None, ['kaohsiung', '高雄']),
    'Hsinchu': ('Taiwan', None, ['hsinchu', '新竹']), 'Keelung': ('Taiwan', None, ['keelung', '基隆']),
    'Changhua': ('Taiwan', None, ['changhua', '彰化']), 'Yilan': ('Taiwan', None, ['yilan', '宜兰', '宜蘭']),
    'Pingtung': ('Taiwan', None, ['屏东', '屏東']), 'Chiayi': ('Taiwan', None, ['嘉义', '嘉義']),
    'Miaoli': ('Taiwan', None, ['苗栗']), 'Nantou': ('Taiwan', None, ['南投']), 'Yunlin': ('Taiwan', None, ['云林', '雲林']),
    'Hualien': ('Taiwan', None, ['花莲', '花蓮']), 'Taitung': ('Taiwan', None, ['台东', '臺東', '台東']),
    'Tokyo': ('Japan', None, ['tokyo', '东京', '東京']), 'Osaka': ('Japan', None, ['osaka', '大阪']),
    'Kyoto': ('Japan', None, ['kyoto']), 'Seoul': ('South Korea', None, ['seoul']),
    'Bangalore': ('India', None, ['bengaluru', 'bangalore']), 'Mumbai': ('India', None, ['mumbai']),
    'Delhi': ('India', None, ['new delhi', 'delhi', 'gurgaon', 'gurugram', 'noida']),
    'Hyderabad': ('India', None, ['hyderabad']), 'Pune': ('India', None, ['pune']), 'Chennai': ('India', None, ['chennai']),
    'Manila': ('Philippines', None, ['manila', 'makati', 'taguig']), 'Jakarta': ('Indonesia', None, ['jakarta']),
    'Kuala Lumpur': ('Malaysia', None, ['kuala lumpur']), 'Bangkok': ('Thailand', None, ['bangkok']),
    'Ho Chi Minh City': ('Vietnam', None, ['ho chi minh']), 'Hanoi': ('Vietnam', None, ['hanoi']),
    'San Francisco Bay Area': ('United States', 'CA', [
        'san francisco', 'bay area', 'silicon valley', 'oakland', 'san jose', 'palo alto', 'mountain view', 'menlo park',
        'sunnyvale', 'redwood city', 'san mateo', 'foster city', 'santa clara', 'cupertino', 'berkeley', 'emeryville',
        'burlingame', 'san bruno', 'fremont']),
    'Los Angeles': ('United States', 'CA', ['los angeles', 'santa monica', 'culver city', 'pasadena', 'irvine']),
    'San Diego': ('United States', 'CA', ['san diego']),
    'New York': ('United States', 'NY', ['new york city', 'new york', 'nyc', 'brooklyn', 'manhattan']),
    'Seattle': ('United States', 'WA', ['seattle', 'bellevue', 'redmond', 'kirkland']),
    'Boston': ('United States', 'MA', ['boston', 'somerville']), 'Chicago': ('United States', 'IL', ['chicago']),
    'Austin': ('United States', 'TX', ['austin']), 'Dallas': ('United States', 'TX', ['dallas', 'westlake', 'plano']),
    'Houston': ('United States', 'TX', ['houston']), 'Denver': ('United States', 'CO', ['denver', 'boulder']),
    'Philadelphia': ('United States', 'PA', ['philadelphia']), 'Pittsburgh': ('United States', 'PA', ['pittsburgh']),
    'Phoenix': ('United States', 'AZ', ['phoenix', 'scottsdale', 'tempe']),
    'Portland': ('United States', 'OR', ['portland']), 'Santa Fe': ('United States', 'NM', ['santa fe']),
    'Atlanta': ('United States', 'GA', ['atlanta']), 'Miami': ('United States', 'FL', ['miami']),
    'Washington DC': ('United States', 'DC', ['washington, d.c.', 'washington d.c.', 'washington, dc', 'washington dc',
                                              'district of columbia']),
    'Salt Lake City': ('United States', 'UT', ['salt lake city']), 'Nashville': ('United States', 'TN', ['nashville']),
    'Minneapolis': ('United States', 'MN', ['minneapolis']),
    'Toronto': ('Canada', 'ON', ['toronto']), 'Ottawa': ('Canada', 'ON', ['ottawa']),
    'Kitchener-Waterloo': ('Canada', 'ON', ['kitchener', 'waterloo']),
    'Vancouver': ('Canada', 'BC', ['vancouver', 'burnaby']), 'Montreal': ('Canada', 'QC', ['montreal', 'montréal']),
    'Calgary': ('Canada', 'AB', ['calgary']), 'Halifax': ('Canada', 'NS', ['halifax']),
    'Mexico City': ('Mexico', None, ['mexico city', 'ciudad de méxico']),
    'São Paulo': ('Brazil', None, ['são paulo', 'sao paulo']), 'Buenos Aires': ('Argentina', None, ['buenos aires']),
    'Bogotá': ('Colombia', None, ['bogotá', 'bogota']),
    'London': ('United Kingdom', None, ['london']), 'Manchester': ('United Kingdom', None, ['manchester']),
    'Edinburgh': ('United Kingdom', None, ['edinburgh']), 'Glasgow': ('United Kingdom', None, ['glasgow']),
    'Cardiff': ('United Kingdom', None, ['cardiff']), 'Bristol': ('United Kingdom', None, ['bristol']),
    'Dublin': ('Ireland', None, ['dublin']), 'Cork': ('Ireland', None, ['cork']),
    'Berlin': ('Germany', None, ['berlin']), 'Munich': ('Germany', None, ['munich', 'münchen']),
    'Hamburg': ('Germany', None, ['hamburg']), 'Frankfurt': ('Germany', None, ['frankfurt']),
    'Paris': ('France', None, ['paris']), 'Amsterdam': ('Netherlands', None, ['amsterdam']),
    'Madrid': ('Spain', None, ['madrid']), 'Barcelona': ('Spain', None, ['barcelona']),
    'Lisbon': ('Portugal', None, ['lisbon', 'lisboa']), 'Milan': ('Italy', None, ['milan', 'milano']),
    'Zurich': ('Switzerland', None, ['zurich', 'zürich']), 'Warsaw': ('Poland', None, ['warsaw']),
    'Stockholm': ('Sweden', None, ['stockholm']), 'Sofia': ('Bulgaria', None, ['sofia']),
    'Belgrade': ('Serbia', None, ['belgrade']), 'Tel Aviv': ('Israel', None, ['tel aviv']),
    'Dubai': ('United Arab Emirates', None, ['dubai']), 'Abu Dhabi': ('United Arab Emirates', None, ['abu dhabi']),
    'Sydney': ('Australia', None, ['sydney']), 'Melbourne': ('Australia', None, ['melbourne', '墨尔本']),
    'Brisbane': ('Australia', None, ['brisbane']), 'Perth': ('Australia', None, ['perth']),
    'Auckland': ('New Zealand', None, ['auckland']), 'Wellington': ('New Zealand', None, ['wellington']),
    # 11-07: cities in postings the list above missed (Arbeitnow gives only the city)
    'Cologne': ('Germany', None, ['cologne', 'köln', 'koeln']), 'Düsseldorf': ('Germany', None, ['düsseldorf', 'dusseldorf']),
    'Stuttgart': ('Germany', None, ['stuttgart']), 'Karlsruhe': ('Germany', None, ['karlsruhe']),
    'Essen': ('Germany', None, ['essen']), 'Bochum': ('Germany', None, ['bochum']),
    'Dortmund': ('Germany', None, ['dortmund']), 'Dresden': ('Germany', None, ['dresden']),
    'Leipzig': ('Germany', None, ['leipzig']), 'Aachen': ('Germany', None, ['aachen']),
    'Kassel': ('Germany', None, ['kassel']), 'Nuremberg': ('Germany', None, ['nuremberg', 'nürnberg']),
    'Hanover': ('Germany', None, ['hanover', 'hannover']), 'Ulm': ('Germany', None, ['ulm']),
    'Bonn': ('Germany', None, ['bonn']), 'Mannheim': ('Germany', None, ['mannheim']),
    'Heidelberg': ('Germany', None, ['heidelberg']), 'Bremen': ('Germany', None, ['bremen']),
    'Wiesbaden': ('Germany', None, ['wiesbaden']), 'Mainz': ('Germany', None, ['mainz']),
    'Darmstadt': ('Germany', None, ['darmstadt']), 'Augsburg': ('Germany', None, ['augsburg']),
    'Freiburg': ('Germany', None, ['freiburg']), 'Münster': ('Germany', None, ['münster']),
    'Potsdam': ('Germany', None, ['potsdam']), 'Regensburg': ('Germany', None, ['regensburg']),
    'Bern': ('Switzerland', None, ['bern']), 'Geneva': ('Switzerland', None, ['geneva', 'genève', 'genf']),
    'Basel': ('Switzerland', None, ['basel']), 'Lausanne': ('Switzerland', None, ['lausanne']),
    'Zug': ('Switzerland', None, ['zug']), 'Lucerne': ('Switzerland', None, ['lucerne', 'luzern']),
    'Winterthur': ('Switzerland', None, ['winterthur']), 'Nyon': ('Switzerland', None, ['nyon']),
    'Lyon': ('France', None, ['lyon']), 'Bordeaux': ('France', None, ['bordeaux']),
    'Toulouse': ('France', None, ['toulouse']), 'Nantes': ('France', None, ['nantes']),
    'Lille': ('France', None, ['lille']), 'Marseille': ('France', None, ['marseille']),
    'Grenoble': ('France', None, ['grenoble']),
    'Rotterdam': ('Netherlands', None, ['rotterdam']), 'Utrecht': ('Netherlands', None, ['utrecht']),
    'The Hague': ('Netherlands', None, ['the hague', 'den haag']), 'Delft': ('Netherlands', None, ['delft']),
    'Eindhoven': ('Netherlands', None, ['eindhoven']), 'Brussels': ('Belgium', None, ['brussels', 'bruxelles']),
    'Antwerp': ('Belgium', None, ['antwerp', 'antwerpen']), 'Vienna': ('Austria', None, ['vienna', 'wien']),
    'Prague': ('Czechia', None, ['prague', 'praha']), 'Budapest': ('Hungary', None, ['budapest']),
    'Bucharest': ('Romania', None, ['bucharest', 'bucurești']), 'Copenhagen': ('Denmark', None, ['copenhagen']),
    'Oslo': ('Norway', None, ['oslo']), 'Helsinki': ('Finland', None, ['helsinki']),
    'Athens': ('Greece', None, ['athens']), 'Kyiv': ('Ukraine', None, ['kyiv', 'kiev']),
    'Vilnius': ('Lithuania', None, ['vilnius']), 'Tallinn': ('Estonia', None, ['tallinn']),
    'Riga': ('Latvia', None, ['riga']), 'Krakow': ('Poland', None, ['krakow', 'kraków']),
    'Wroclaw': ('Poland', None, ['wroclaw', 'wrocław']), 'Gdansk': ('Poland', None, ['gdansk', 'gdańsk']),
    'Porto': ('Portugal', None, ['porto']), 'Valencia': ('Spain', None, ['valencia']),
    'Rome': ('Italy', None, ['rome', 'roma']), 'Turin': ('Italy', None, ['turin', 'torino']),
    'Zagreb': ('Croatia', None, ['zagreb']), 'Ljubljana': ('Slovenia', None, ['ljubljana']),
    'Bratislava': ('Slovakia', None, ['bratislava']), 'Reykjavik': ('Iceland', None, ['reykjavik', 'reykjavík']),
    'Istanbul': ('Turkey', None, ['istanbul']), 'Cairo': ('Egypt', None, ['cairo']),
    'Lagos': ('Nigeria', None, ['lagos']), 'Nairobi': ('Kenya', None, ['nairobi']),
    'Johannesburg': ('South Africa', None, ['johannesburg', 'sandton']),
    'Cape Town': ('South Africa', None, ['cape town']), 'Riyadh': ('Saudi Arabia', None, ['riyadh']),
    'Doha': ('Qatar', None, ['doha']), 'Beirut': ('Lebanon', None, ['beirut']),
    'Kuwait City': ('Kuwait', None, ['kuwait city']), 'Amman': ('Jordan', None, ['amman']),
    'Casablanca': ('Morocco', None, ['casablanca']), 'Tbilisi': ('Georgia', None, ['tbilisi']),
    'Heredia': ('Costa Rica', None, ['heredia']), 'Montevideo': ('Uruguay', None, ['montevideo']),
    'Medellín': ('Colombia', None, ['medellín', 'medellin']), 'Lima': ('Peru', None, ['lima']),
    'Santiago': ('Chile', None, ['santiago de chile']), 'Guadalajara': ('Mexico', None, ['guadalajara']),
    'Monterrey': ('Mexico', None, ['monterrey']),
}
EUROPE = ['United Kingdom', 'Ireland', 'Germany', 'France', 'Netherlands', 'Belgium', 'Luxembourg', 'Spain', 'Portugal',
          'Italy', 'Switzerland', 'Austria', 'Poland', 'Czechia', 'Hungary', 'Romania', 'Bulgaria', 'Serbia', 'Greece',
          'Ukraine', 'Lithuania', 'Estonia', 'Latvia', 'Sweden', 'Norway', 'Denmark', 'Finland']
LATAM = ['Mexico', 'Brazil', 'Argentina', 'Colombia', 'Chile', 'Peru', 'Costa Rica']
# Top level of the region listing (11-07). Turkey and the Caucasus follow common job-board usage.
CONTINENTS = {
    'Asia': ['China', 'Taiwan', 'Hong Kong', 'Japan', 'South Korea', 'Singapore', 'Malaysia', 'Indonesia', 'Vietnam',
             'Thailand', 'Philippines', 'India', 'Pakistan', 'Sri Lanka', 'Bangladesh', 'Nepal', 'Cambodia',
             'Kazakhstan'],
    'Europe': EUROPE + ['Croatia', 'Slovenia', 'Slovakia', 'Cyprus', 'Malta', 'Iceland', 'Bosnia and Herzegovina',
                        'North Macedonia', 'Albania', 'Montenegro', 'Moldova', 'Armenia', 'Azerbaijan', 'Georgia'],
    'North America': ['United States', 'Canada'],
    'Latin America': LATAM + ['Guatemala', 'Honduras', 'El Salvador', 'Nicaragua', 'Panama', 'Dominican Republic',
                              'Puerto Rico', 'Jamaica', 'Trinidad and Tobago', 'Barbados', 'Bahamas', 'Cuba', 'Haiti',
                              'Uruguay', 'Paraguay', 'Ecuador', 'Bolivia', 'Venezuela'],
    'Middle East & Africa': ['Turkey', 'Israel', 'United Arab Emirates', 'Qatar', 'Saudi Arabia', 'Egypt', 'Nigeria',
                             'Kenya', 'South Africa', 'Lebanon', 'Jordan', 'Kuwait', 'Bahrain', 'Oman', 'Morocco',
                             'Tunisia', 'Ghana', 'Ethiopia', 'Uganda', 'Rwanda', 'Tanzania'],
    'Oceania': ['Australia', 'New Zealand'],
}
CONTINENT = {c: k for k, cs in CONTINENTS.items() for c in cs}
GROUPS = {  # region names that span countries or provinces: aliases -> paths
    ('europe', 'eu', 'emea', '欧洲'): [(x,) for x in CONTINENTS['Europe']],
    ('latam', 'latin america', 'south america', '拉美', '南美'): [(x,) for x in CONTINENTS['Latin America']],
    ('north america', 'amer', '北美'): [('United States',), ('Canada',), ('Mexico',)],
    ('americas',): [(x,) for x in CONTINENTS['North America'] + CONTINENTS['Latin America']],
    ('southeast asia', '东南亚'): [(x,) for x in ('Singapore', 'Malaysia', 'Indonesia', 'Vietnam', 'Thailand',
                                                    'Philippines', 'Cambodia')],
    ('apac', 'asia pacific', '亚太'): [(x,) for x in CONTINENTS['Asia'] + CONTINENTS['Oceania']],
    ('asia', '亚洲'): [(x,) for x in CONTINENTS['Asia']],
    ('middle east', 'mena', '中东'): [(x,) for x in ('Turkey', 'Israel', 'United Arab Emirates', 'Qatar', 'Saudi Arabia',
                                                   'Egypt', 'Lebanon', 'Jordan', 'Kuwait', 'Bahrain', 'Oman')],
    ('africa', '非洲'): [(x,) for x in ('Egypt', 'Nigeria', 'Kenya', 'South Africa', 'Morocco', 'Tunisia', 'Ghana',
                                       'Ethiopia', 'Uganda', 'Rwanda', 'Tanzania')],
    ('oceania', '大洋洲'): [(x,) for x in CONTINENTS['Oceania']],
    ('south china', '华南'): [('China', 'Guangdong'), ('China', 'Guangxi'), ('China', 'Hainan'), ('China', 'Fujian')],
}
ANYWHERE = re.compile(r'(?i)\b(anywhere|worldwide|global(ly)?|world)\b|不限地点|全球')


def _table() -> list[tuple[re.Pattern, bool, list[tuple]]]:
    rows: list[tuple[str, bool, list[tuple]]] = []  # (alias, upper-case code, paths)
    for c, al in COUNTRIES.items():
        rows += [(a, False, [(c,)]) for a in al]
    rows += [(code, True, [(c,)]) for code, c in CODES.items()]
    for code, name in US_STATES.items():
        rows += [(code, True, [('United States', code)])] + ([(name, False, [('United States', code)])] if name else [])
    for code, name in CA_PROVINCES.items():
        rows += [(code, True, [('Canada', code)]), (name, False, [('Canada', code)])]
    for en, zh in CN_PROVINCES.items():
        rows += [(en.lower(), False, [('China', en)]), (zh, False, [('China', en)])]
    for city, (c, region, al) in CITIES.items():
        rows += [(a, False, [(c, region, city) if region else (c, city)]) for a in al]
    for al, paths in GROUPS.items():
        rows += [(a.upper(), True, paths) if a in ('eu', 'emea', 'amer', 'apac', 'latam') else (a, False, paths)
                 for a in al]
    rows.sort(key=lambda x: -len(x[0]))  # longest first: 'new york city' before 'new york', 'western' never matters
    out = []
    for a, cs, paths in rows:
        body = re.escape(a)
        rx = body if re.search(r'[㐀-鿿]', a) else rf'(?<![A-Za-z]){body}(?![A-Za-z])'
        out.append((re.compile(rx if cs else f'(?i){rx}'), cs, paths))
    return out


_TABLE = _table()


def parse(s: str | None) -> list[tuple]:
    """Most specific places named in s (see the module docstring); [] if none or if s says anywhere."""
    s = (s or '')[:300]
    if not s or ANYWHERE.search(s):
        return []
    taken = [False] * len(s)
    named, coded = [], []  # coded: two-letter codes, weaker ('Toronto, ON, CA': CA is Canada here, not California)
    for rx, code, paths in _TABLE:
        for m in rx.finditer(s):
            if any(taken[m.start():m.end()]):
                continue
            taken[m.start():m.end()] = [True] * (m.end() - m.start())
            (coded if code else named).extend(paths)
    sure = {p[0] for p in named}
    found = list(dict.fromkeys(named + [p for p in coded if not sure or p[0] in sure]))
    return [p for p in found if not any(q != p and q[:len(p)] == p for q in found)]  # drop 'US' when 'Austin' is there


def fits(asked: list[tuple], have: list[tuple]) -> bool:
    """True if some named place of the posting may be the asked place (one path a prefix of the other)."""
    return any(a[:len(h)] == h[:len(a)] for a in asked for h in have)


def countries(paths: list[tuple]) -> list[tuple]:
    return list(dict.fromkeys(p[:1] for p in paths))


def name(paths: list[tuple]) -> str:
    return ' / '.join(dict.fromkeys(p[-1] for p in paths[:3])) + (' …' if len(paths) > 3 else '')


def classify(o) -> list[str]:
    """Where a posting is (11-07), as stored in opp_places: its most specific places joined with '/'
    ('China/Zhejiang/Hangzhou'), ['*'] when its location says anywhere / worldwide or it is a GitHub bounty (anyone can
    take one), [] when no place is known. Location and title both count, as for the mismatch tag ('广东' + '（武汉广州杭州）'),
    but a region naming more than 3 countries in the title of a posting with a place does not ('Singapore' +
    'Asia-Pacific'). A title place beats an anywhere location (WWR: 'Remote (Anywhere in the World)' on
    '... (USA Only, 100% Remote)'). SmartRecruiters
    ends every location with an ISO country code ('Speyer, RP, DE'), which wins over a place name in another country."""
    loc = o['location'] or ''
    if o['source'] == 'github':
        return ['*']
    if ANYWHERE.search(loc):
        return ['/'.join(p) for p in parse(o['title'])] or ['*']
    have, more = parse(loc), parse(o['title'])
    if have and len({p[0] for p in more}) > 3:  # a region in the title of a posting with a place: Singapore, '(APAC)'
        more = []
    have += more
    if o['source'] == 'smartrecruiters' and ',' in loc:
        iso = ISO2.get(loc.rsplit(',', 1)[1].strip())
        if iso:
            have = [p for p in have if p[0] == iso] or [(iso,)]
    have = list(dict.fromkeys(have))
    return ['/'.join(p) for p in have if not any(q != p and q[:len(p)] == p for q in have)]


def label(path: str) -> str:
    """'China/Zhejiang/Hangzhou' -> 'Hangzhou, Zhejiang, China'; '*' -> 'anywhere'."""
    return 'anywhere' if path == '*' else ', '.join(reversed(path.split('/')))
