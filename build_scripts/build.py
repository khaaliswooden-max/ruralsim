import sys, re, json, warnings
import pandas as pd, numpy as np
warnings.filterwarnings('ignore')
RAW, OUT = sys.argv[1], sys.argv[2]
cb = []  # codebook rows
def doc(table, col, desc, source, vintage, prov='observed'):
    cb.append(dict(table=table, column=col, description=desc, source=source, vintage=vintage, provenance=prov))
z5 = lambda s: s.astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.zfill(5)
num = lambda s: pd.to_numeric(s.astype(str).str.replace(',', '').str.strip(), errors='coerce')

# ---------- spine ----------
gaz = pd.read_csv(f'{RAW}/gaz/2024_Gaz_counties_national.txt', sep='\t', dtype=str)
gaz.columns = [c.strip() for c in gaz.columns]
m = pd.DataFrame({'fips5': gaz.GEOID, 'state_abbr': gaz.USPS, 'county_name': gaz.NAME,
                  'land_area_sqmi': num(gaz.ALAND_SQMI), 'water_area_sqmi': num(gaz.AWATER_SQMI),
                  'centroid_lat': num(gaz.INTPTLAT), 'centroid_lon': num(gaz.INTPTLONG)})
m = m[~m.state_abbr.isin(['PR'])]
m['state_fips'] = m.fips5.str[:2]
m['geography_vintage'] = '2024'
m['is_ct_planning_region'] = m.fips5.str.match(r'^091[1-9]0$')
m['is_ak_borough_or_census_area'] = m.state_fips.eq('02')
m['is_va_independent_city'] = m.state_fips.eq('51') & (m.fips5.str[2:].astype(int) >= 500)

# RUCC 2023 (long)
r = pd.read_csv(f'{RAW}/ers_rucc/rucc2023.csv', encoding='latin1', dtype=str)
r = r.pivot_table(index='FIPS', columns='Attribute', values='Value', aggfunc='first').reset_index()
r23 = pd.DataFrame({'fips5': z5(r.FIPS), 'rucc_2023': num(r.RUCC_2023), 'pop_2020_census': num(r.Population_2020)})
def xl(f, fcol, mapping):
    d = pd.read_excel(f'{RAW}/ers_rucc/{f}', dtype=str)
    o = pd.DataFrame({'fips5': z5(d[fcol])})
    for new, old in mapping.items(): o[new] = num(d[old])
    return o.drop_duplicates('fips5')
r13 = xl('rucc2013.xls', 'FIPS', {'rucc_2013': 'RUCC_2013', 'pop_2010_census': 'Population_2010'})
r03 = xl('rucc2003.xls', 'FIPS Code', {'rucc_2003': '2003 Rural-urban Continuum Code', 'pop_2000_census': '2000 Population '})
r8393 = xl('rucc1983_1993.xls', 'FIPS', {'rucc_1983': '1983 Rural-urban Continuum Code', 'rucc_1993': '1993 Rural-urban Continuum Code'})
r74 = xl('rucc1974.xls', 'FIPS Code', {'rucc_1974': '1974 Rural-urban Continuum Code'})
rucc_all = r23.merge(r13, 'outer', 'fips5').merge(r03, 'outer', 'fips5').merge(r8393, 'outer', 'fips5').merge(r74, 'outer', 'fips5')
rucc_all = rucc_all[rucc_all.fips5.str.match(r'^\d{5}$')]
rucc_all = rucc_all[rucc_all.fips5.str[:2].astype(int) <= 56]
# legacy counties not in 2024 gazetteer (e.g. old CT counties) are added to the spine and flagged
legacy = rucc_all[~rucc_all.fips5.isin(m.fips5) & ~rucc_all.fips5.str.endswith('000')][['fips5']].copy()
legacy = legacy.drop_duplicates('fips5'); legacy['state_fips'] = legacy.fips5.str[:2]; legacy['geography_vintage'] = 'legacy'
m = pd.concat([m, legacy], ignore_index=True)
m = m.merge(rucc_all, 'left', 'fips5')
m['nonmetro_2023'] = np.where(m.rucc_2023.notna(), m.rucc_2023 >= 4, np.nan)

# Census 2020 urban/rural
ua = pd.read_excel(f'{RAW}/census_ua/2020_UA_COUNTY.xlsx', sheet_name='2020_UA_COUNTY', dtype=str)
u = pd.DataFrame({'fips5': ua.STATE.str.zfill(2) + ua.COUNTY.str.zfill(3), 'pop_2020_ua_file': num(ua.POP_COU),
                  'housing_units_2020': num(ua.HOU_COU), 'pop_rural_2020': num(ua.POP_RUR), 'pop_urban_2020': num(ua.POP_URB),
                  'pop_density_2020_per_sqmi': num(ua.POPDEN_COU), 'housing_density_2020_per_sqmi': num(ua.HOUDEN_COU)})
u['census_rural_share_2020'] = u.pop_rural_2020 / u.pop_2020_ua_file
try:
    ct = pd.read_excel(f'{RAW}/census_ua/2020_UA_COUNTY.xlsx', sheet_name='CT_2022', dtype=str)
    c2 = pd.DataFrame({'fips5': ct.STATE.str.zfill(2) + ct.COUNTY.str.zfill(3), 'pop_2020_ua_file': num(ct.POP_COU),
                       'housing_units_2020': num(ct.HOU_COU), 'pop_rural_2020': num(ct.POP_RUR), 'pop_urban_2020': num(ct.POP_URB),
                       'pop_density_2020_per_sqmi': num(ct.POPDEN_COU), 'housing_density_2020_per_sqmi': num(ct.HOUDEN_COU)})
    c2['census_rural_share_2020'] = c2.pop_rural_2020 / c2.pop_2020_ua_file
    u = pd.concat([u, c2[~c2.fips5.isin(u.fips5)]])
except Exception as e: print('CT sheet:', e)
m = m.merge(u, 'left', 'fips5')
m['pop_2020_census'] = m.pop_2020_census.fillna(m.pop_2020_ua_file); m = m.drop(columns='pop_2020_ua_file')

# typology 2025
t = pd.read_csv(f'{RAW}/ers_typ/typology2025.csv', encoding='latin1', dtype=str)
t = t.pivot_table(index='FIPStxt', columns='Attribute', values='Value', aggfunc='first').reset_index()
t.columns = ['fips5'] + ['typ_' + c.lower() for c in t.columns[1:]]
t['fips5'] = z5(t.fips5); t = t[t.fips5.str.match(r'^\d{5}$')]
for c in t.columns[1:]: t[c] = num(t[c])
m = m.merge(t, 'left', 'fips5')

# hospitals (CMS Hospital General Information, current snapshot)
h = pd.read_csv(f'{RAW}/cms/hospitals.csv', dtype=str)
def norm(s):
    s = s.fillna('').str.upper().str.replace(r"[.'\-]", '', regex=True)
    s = s.str.replace(r'\b(COUNTY|PARISH|BOROUGH|CENSUS AREA|MUNICIPALITY|CITY AND BOROUGH|PLANNING REGION)\b', '', regex=True)
    s = s.str.replace(r'^SAINT ', 'ST ', regex=True).str.replace(r'^STE ', 'STE ', regex=True)
    return s.str.replace(r'\s+', '', regex=True)
key = m[m.geography_vintage.eq('2024')][['fips5', 'state_abbr', 'county_name']].copy()
key['k'] = key.state_abbr + '|' + norm(key.county_name)
vc = key[key.county_name.str.contains(' city', na=False)].copy(); vc['k'] = vc.state_abbr + '|' + norm(vc.county_name.str.replace(' city', '')) + 'CITY'
kmap = pd.concat([key, vc]).drop_duplicates('k').set_index('k').fips5
h['k'] = h.State + '|' + norm(h['County/Parish'])
h['fips5'] = h.k.map(kmap)
hosp_match = h.fips5.notna().mean()
hg = h.dropna(subset=['fips5']).groupby('fips5').agg(
    n_hospitals=('Facility ID', 'count'),
    n_critical_access_hospitals=('Hospital Type', lambda s: (s == 'Critical Access Hospitals').sum()),
    n_rural_emergency_hospitals=('Hospital Type', lambda s: (s == 'Rural Emergency Hospital').sum()),
    n_acute_care_hospitals=('Hospital Type', lambda s: (s == 'Acute Care Hospitals').sum()),
    n_hospitals_with_emergency=('Emergency Services', lambda s: (s == 'Yes').sum())).reset_index()
m = m.merge(hg, 'left', 'fips5')
for c in hg.columns[1:]: m.loc[m.geography_vintage.eq('2024'), c] = m.loc[m.geography_vintage.eq('2024'), c].fillna(0)
h[['Facility ID', 'Facility Name', 'Address', 'City/Town', 'State', 'ZIP Code', 'County/Parish', 'Hospital Type', 'Hospital Ownership', 'Emergency Services', 'fips5']].to_csv(f'{OUT}/facility_hospital.csv', index=False)

# SAIPE 2023
s = pd.read_excel(f'{RAW}/saipe/est23all.xls', header=3, dtype=str)
sc = list(s.columns)
sa = pd.DataFrame({'fips5': s[sc[0]].str.zfill(2) + s[sc[1]].str.zfill(3)})
def pick(pat, nth=0): return [c for c in sc if re.search(pat, c)][nth]
sa['poverty_rate_2023'] = num(s[pick(r'^Poverty Percent, All Ages')]); i = sc.index(pick(r'^Poverty Percent, All Ages'))
sa['poverty_rate_2023_ci90_lo'] = num(s[sc[i + 1]]); sa['poverty_rate_2023_ci90_hi'] = num(s[sc[i + 2]])
sa['child_poverty_rate_2023'] = num(s[pick(r'^Poverty Percent, Age 0-17')])
sa['median_hh_income_2023'] = num(s[pick(r'^Median Household Income')]); i = sc.index(pick(r'^Median Household Income'))
sa['median_hh_income_2023_ci90_lo'] = num(s[sc[i + 1]]); sa['median_hh_income_2023_ci90_hi'] = num(s[sc[i + 2]])
m = m.merge(sa, 'left', 'fips5')

# ---------- county_year ----------
def popest(f, years):
    d = pd.read_csv(f, encoding='latin1', dtype=str); d = d[d.SUMLEV == '050']
    d['fips5'] = d.STATE.str.zfill(2) + d.COUNTY.str.zfill(3)
    rows = []
    for y in years:
        o = pd.DataFrame({'fips5': d.fips5, 'year': y})
        for new, old in dict(population='POPESTIMATE', births='BIRTHS', deaths='DEATHS', natural_change='NATURALCHG' if f'NATURALCHG{y}' in d else 'NATURALINC',
                             international_migration='INTERNATIONALMIG', domestic_migration='DOMESTICMIG', net_migration='NETMIG').items():
            o[new] = num(d[f'{old}{y}']) if f'{old}{y}' in d else np.nan
        rows.append(o)
    return pd.concat(rows)
cy = pd.concat([popest(f'{RAW}/popest/co-est2020-alldata.csv', range(2010, 2020)).assign(popest_vintage='2020'),
                popest(f'{RAW}/popest/co-est2024-alldata.csv', range(2020, 2025)).assign(popest_vintage='2024')])
cy.loc[cy.year.isin([2010, 2020]), ['births', 'deaths', 'natural_change', 'international_migration', 'domestic_migration', 'net_migration']] = np.nan  # partial-year values (Apr-Jun) removed
cy = cy.sort_values(['fips5', 'year'])
cy['pop_change_pct'] = cy.groupby('fips5').population.pct_change() * 100
cy.loc[cy.year.eq(2020), 'pop_change_pct'] = np.nan  # vintage break
pe = pd.read_csv(f'{RAW}/popest/co-est2024-alldata.csv', encoding='latin1', dtype=str); pe = pe[pe.SUMLEV == '050']
m = m.merge(pd.DataFrame({'fips5': pe.STATE.str.zfill(2) + pe.COUNTY.str.zfill(3), 'pop_2024_estimate': num(pe.POPESTIMATE2024)}), 'left', 'fips5')
m['pop_change_2020_2024_pct'] = (m.pop_2024_estimate / m.pop_2020_census - 1) * 100

# ---------- county_profile (ERS Atlas, wide) ----------
frames = []
for f in ['People', 'Jobs', 'Income', 'Veterans', 'CountyClassifications']:
    d = pd.read_csv(f'{RAW}/ers_atlas/{f}.csv', encoding='latin1', dtype=str)
    d = d.iloc[:, :5]; d.columns = ['FIPS', 'State', 'County', 'Attribute', 'Value']
    frames.append(d)
a = pd.concat(frames); a['fips5'] = z5(a.FIPS); a['Value'] = num(a.Value)
a = a[a.fips5.str.match(r'^\d{5}$')]
a = a[~a.fips5.str.endswith('000') & (a.fips5.str[:2].astype(int) <= 56)]
prof = a.pivot_table(index='fips5', columns='Attribute', values='Value', aggfunc='first').reset_index()
look = pd.read_csv(f'{RAW}/ers_atlas/VariableNameLookup.csv', encoding='latin1', dtype=str).set_index('varShort').varLong.to_dict()

# ---------- county_decade ----------
nb = pd.read_csv(f'{RAW}/nber/cencounts.csv', dtype=str)
nb = nb[nb.fips.str.match(r'^\d{5}$', na=False) & ~nb.fips.str.endswith('000', na=True)]
dec = nb.melt(id_vars=['fips', 'name'], var_name='y', value_name='population')
dec['year'] = dec.y.str[3:].astype(int); dec['population'] = num(dec.population); dec = dec.rename(columns={'fips': 'fips5'})[['fips5', 'year', 'population']]
dec['source'] = 'Census historical county counts via NBER cencounts'
add = [m[['fips5', 'pop_2000_census']].rename(columns={'pop_2000_census': 'population'}).assign(year=2000, source='ERS RUCC 2003 file (Census 2000)'),
       m[['fips5', 'pop_2010_census']].rename(columns={'pop_2010_census': 'population'}).assign(year=2010, source='ERS RUCC 2013 file (Census 2010)'),
       m[['fips5', 'pop_2020_census']].rename(columns={'pop_2020_census': 'population'}).assign(year=2020, source='ERS RUCC 2023 / Census 2020 UA file')]
dec = pd.concat([dec] + add).dropna(subset=['population']); dec = dec[dec.population > 0].drop_duplicates(['fips5', 'year']).sort_values(['fips5', 'year']).reset_index(drop=True)
dec['pop_change_pct_decade'] = dec.groupby('fips5').population.pct_change() * 100
pk = dec.loc[dec.groupby('fips5').population.idxmax()][['fips5', 'year', 'population']].rename(columns={'year': 'peak_pop_decade', 'population': 'peak_pop'})
m = m.merge(pk, 'left', 'fips5'); m['pop_2020_pct_of_peak'] = m.pop_2020_census / m.peak_pop * 100
m = m.merge(dec[dec.year == 1900][['fips5', 'population']].rename(columns={'population': 'pop_1900_census'}), 'left', 'fips5')

# ---------- county_election ----------
import pyreadr
al = list(pyreadr.read_r(f'{RAW}/algara/pres_county.Rdata').values())[0]
e = pd.DataFrame({'fips5': z5(al.fips), 'year': al.election_year.astype(int), 'office': 'PRESIDENT', 'dem_votes': al.democratic_raw_votes,
                  'rep_votes': al.republican_raw_votes, 'total_votes': al.raw_county_vote_totals, 'dem_nominee': al.dem_nominee, 'rep_nominee': al.rep_nominee,
                  'source': 'Algara & Amlani 2021 (doi:10.7910/DVN/DGUMFI)'})
tm = pd.read_csv(f'{RAW}/tonmcg/2024.csv', dtype=str)
e24 = pd.DataFrame({'fips5': z5(tm.county_fips), 'year': 2024, 'office': 'PRESIDENT', 'dem_votes': num(tm.votes_dem), 'rep_votes': num(tm.votes_gop),
                    'total_votes': num(tm.total_votes), 'dem_nominee': 'Kamala Harris', 'rep_nominee': 'Donald Trump',
                    'source': 'tonmcg/US_County_Level_Election_Results_08-24 (GitHub; unofficial compilation)'})
e = pd.concat([e, e24]).drop_duplicates(['fips5', 'year'])
e['other_votes'] = (e.total_votes - e.dem_votes.fillna(0) - e.rep_votes.fillna(0)).clip(lower=0)
tp = e.dem_votes + e.rep_votes
e['two_party_dem_share'] = e.dem_votes / tp
e['margin_rd'] = (e.rep_votes - e.dem_votes) / e.total_votes
nat = e.groupby('year').apply(lambda g: g.dem_votes.sum() / (g.dem_votes.sum() + g.rep_votes.sum())).rename('nat')
e = e.merge(nat, left_on='year', right_index=True)
e['lean_vs_nation'] = e.two_party_dem_share - e.nat; e = e.drop(columns='nat')
e = e.sort_values(['fips5', 'year'])
e['swing_vs_prev'] = e.groupby('fips5').margin_rd.diff()
e['in_current_spine'] = e.fips5.isin(m.fips5)
lat = e[e.year.isin([2016, 2020, 2024])].pivot_table(index='fips5', columns='year', values='margin_rd').reset_index()
lat.columns = ['fips5'] + [f'pres_margin_rd_{c}' for c in lat.columns[1:]]
m = m.merge(lat, 'left', 'fips5')

# ---------- state_decade_power ----------
ap = pd.read_csv(f'{RAW}/apport/apportionment.csv', dtype=str); ap = ap[ap['Geography Type'] == 'State']
sp = pd.DataFrame({'state_name': ap.Name, 'year': ap.Year.astype(int), 'resident_pop': num(ap['Resident Population']), 'house_seats': num(ap['Number of Representatives'])})
sp = sp[sp.house_seats.notna() & ~sp.state_name.isin(['District of Columbia', 'Puerto Rico'])]
sp['electoral_votes'] = sp.house_seats + 2
g = sp.groupby('year')
sp['pop_share'] = sp.resident_pop / g.resident_pop.transform('sum')
sp['n_states'] = g.state_name.transform('count')
sp['senate_weight_index'] = (2 / (2 * sp.n_states)) / sp.pop_share
sp['house_weight_index'] = (sp.house_seats / g.house_seats.transform('sum')) / sp.pop_share
sp['ec_weight_index'] = (sp.electoral_votes / g.electoral_votes.transform('sum')) / sp.pop_share
sp['persons_per_senator'] = sp.resident_pop / 2
sp['persons_per_house_seat'] = sp.resident_pop / sp.house_seats
names = {'AL':'Alabama','AK':'Alaska','AZ':'Arizona','AR':'Arkansas','CA':'California','CO':'Colorado','CT':'Connecticut','DE':'Delaware','FL':'Florida','GA':'Georgia','HI':'Hawaii','ID':'Idaho','IL':'Illinois','IN':'Indiana','IA':'Iowa','KS':'Kansas','KY':'Kentucky','LA':'Louisiana','ME':'Maine','MD':'Maryland','MA':'Massachusetts','MI':'Michigan','MN':'Minnesota','MS':'Mississippi','MO':'Missouri','MT':'Montana','NE':'Nebraska','NV':'Nevada','NH':'New Hampshire','NJ':'New Jersey','NM':'New Mexico','NY':'New York','NC':'North Carolina','ND':'North Dakota','OH':'Ohio','OK':'Oklahoma','OR':'Oregon','PA':'Pennsylvania','RI':'Rhode Island','SC':'South Carolina','SD':'South Dakota','TN':'Tennessee','TX':'Texas','UT':'Utah','VT':'Vermont','VA':'Virginia','WA':'Washington','WV':'West Virginia','WI':'Wisconsin','WY':'Wyoming','DC':'District of Columbia'}
cur = m[m.geography_vintage.eq('2024')]
st = cur.groupby('state_abbr').apply(lambda d: pd.Series({
    'census_rural_share': d.pop_rural_2020.sum() / (d.pop_rural_2020.sum() + d.pop_urban_2020.sum()),
    'nonmetro_share': d.loc[d.rucc_2023 >= 4, 'pop_2020_census'].sum() / d.loc[d.rucc_2023.notna(), 'pop_2020_census'].sum()})).reset_index()
st['state_name'] = st.state_abbr.map(names); st['year'] = 2020
sp = sp.merge(st, 'left', ['state_name', 'year'])
lh = sp.groupby('year').apply(lambda d: pd.Series({
    'n_states': len(d), 'us_apportioned_pop': d.resident_pop.sum(),
    'senate_malapportionment_loosemore_hanby': 0.5 * (1 / len(d) - d.pop_share).abs().sum(),
    'house_malapportionment_loosemore_hanby': 0.5 * (d.house_seats / d.house_seats.sum() - d.pop_share).abs().sum(),
    'ec_malapportionment_loosemore_hanby': 0.5 * (d.electoral_votes / d.electoral_votes.sum() - d.pop_share).abs().sum(),
    'pop_share_of_smallest_states_electing_senate_majority': d.sort_values('resident_pop').head(len(d) // 2 + 1).pop_share.sum(),
    'max_min_persons_per_senator_ratio': d.resident_pop.max() / d.resident_pop.min()})).reset_index()
x = sp[sp.year == 2020].dropna(subset=['nonmetro_share'])
rw = dict(year=2020, nonmetro_weighted_senate_index=float((x.senate_weight_index * x.nonmetro_share * x.resident_pop).sum() / (x.nonmetro_share * x.resident_pop).sum()),
          metro_weighted_senate_index=float((x.senate_weight_index * (1 - x.nonmetro_share) * x.resident_pop).sum() / ((1 - x.nonmetro_share) * x.resident_pop).sum()),
          nonmetro_weighted_ec_index=float((x.ec_weight_index * x.nonmetro_share * x.resident_pop).sum() / (x.nonmetro_share * x.resident_pop).sum()),
          metro_weighted_ec_index=float((x.ec_weight_index * (1 - x.nonmetro_share) * x.resident_pop).sum() / ((1 - x.nonmetro_share) * x.resident_pop).sum()))
lh = lh.merge(pd.DataFrame([rw]), 'left', 'year')

# ---------- write ----------
assert m.fips5.is_unique, 'dup fips'
m = m.sort_values('fips5'); prof = prof.sort_values('fips5')
tabs = {'county_master': m, 'county_year': cy, 'county_profile': prof, 'county_decade': dec, 'county_election': e, 'state_decade_power': sp, 'national_power_summary': lh}
for k, v in tabs.items(): v.to_csv(f'{OUT}/{k}.csv', index=False)

# ---------- codebook ----------
D = {
 'fips5': ('5-character county FIPS, zero-padded string. Primary join key.', 'Census Gazetteer 2024 + ERS RUCC legacy codes', '2024'),
 'geography_vintage': ("'2024' = current county-equivalent; 'legacy' = retired code kept for history (e.g. pre-2022 Connecticut counties).", 'derived', '2024'),
 'nonmetro_2023': ('Default rural flag: RUCC 2023 code 4-9.', 'USDA ERS RUCC 2023', '2023'),
 'census_rural_share_2020': ('Share of 2020 population living in Census-defined rural blocks (continuous rural measure).', 'Census 2020 Urban Area county file', '2020'),
 'land_area_sqmi': ('Land area, square miles.', 'Census Gazetteer', '2024'),
 'centroid_lat': ('Internal point latitude.', 'Census Gazetteer', '2024'), 'centroid_lon': ('Internal point longitude.', 'Census Gazetteer', '2024'),
 'peak_pop_decade': ('Census year of maximum population, 1900-2020.', 'derived from county_decade', '1900-2020'),
 'pop_2020_pct_of_peak': ('2020 population as % of historical peak; below 100 means the county has shrunk.', 'derived', '1900-2020'),
 'n_hospitals': ('Medicare-registered hospitals located in county.', 'CMS Hospital General Information', '2026 snapshot'),
 'n_critical_access_hospitals': ('Critical Access Hospitals in county.', 'CMS Hospital General Information', '2026 snapshot'),
 'n_rural_emergency_hospitals': ('Rural Emergency Hospitals in county.', 'CMS Hospital General Information', '2026 snapshot'),
 'poverty_rate_2023': ('All-ages poverty rate, %; model-based, with 90% CI columns.', 'Census SAIPE', '2023'),
 'median_hh_income_2023': ('Median household income, USD; with 90% CI columns.', 'Census SAIPE', '2023'),
 'margin_rd': ('(Republican - Democratic votes) / total votes. Positive = Republican lead.', 'derived', ''),
 'two_party_dem_share': ('Democratic share of the two-party vote.', 'derived', ''),
 'lean_vs_nation': ('County two-party Democratic share minus the national two-party share that year (computed from the counties present).', 'derived', ''),
 'swing_vs_prev': ('Change in margin_rd from the previous presidential election in the same county.', 'derived', ''),
 'senate_weight_index': ("State's share of Senate seats divided by its share of apportioned population. 1.0 = proportional.", 'derived from Census apportionment', '1910-2020'),
 'ec_weight_index': ('Share of electoral votes (House seats + 2) divided by population share. DC excluded.', 'derived', '1910-2020'),
 'house_weight_index': ('Share of House seats divided by population share.', 'derived', '1910-2020'),
 'nonmetro_share': ('Share of state 2020 population in RUCC 4-9 counties.', 'derived', '2020'),
 'census_rural_share': ('Share of state 2020 population in Census rural blocks.', 'derived', '2020'),
 'senate_malapportionment_loosemore_hanby': ('0.5 * sum |seat share - population share| across states.', 'derived', '1910-2020'),
 'nonmetro_weighted_senate_index': ('Average Senate weight index experienced by a nonmetro resident (population-weighted).', 'derived', '2020'),
 'natural_change': ('Births minus deaths, July-to-July year. Blank for 2010 and 2020 (partial-year values removed).', 'Census Population Estimates', 'V2020 / V2024'),
 'pop_change_pct': ('Year-over-year population change, %. Blank at 2020 because the estimate vintage changes.', 'derived', ''),
}
SRC = {'county_master': ('see column', ''), 'county_year': ('Census Population Estimates (Vintage 2020 for 2010-19, Vintage 2024 for 2020-24)', '2010-2024'),
       'county_profile': ('USDA ERS Atlas of Rural and Small-Town America', 'see column name suffix'), 'county_decade': ('Census decennial counts', '1900-2020'),
       'county_election': ('Algara & Amlani 1868-2020; tonmcg GitHub compilation for 2024', '1868-2024'),
       'state_decade_power': ('Census apportionment tables', '1910-2020'), 'national_power_summary': ('derived from state_decade_power', '1910-2020')}
for k, v in tabs.items():
    for c in v.columns:
        if c in D: d, s_, vt = D[c]
        elif k == 'county_profile' and c in look: d, s_, vt = look[c], SRC[k][0], (re.findall(r'(\d{4}|\d{2,4}\d{2})$', c) or [''])[0]
        elif c.startswith('rucc_'): d, s_, vt = f'Rural-Urban Continuum Code, {c[-4:]} edition (1-3 metro, 4-9 nonmetro). 2023 raised the urban floor to 5,000; do not read 2013->2023 changes as real change.', 'USDA ERS', c[-4:]
        elif c.startswith('typ_'): d, s_, vt = f'ERS County Typology flag: {c[4:]}', 'USDA ERS County Typology Codes, 2025 edition', '2025'
        elif c.startswith('pres_margin_rd_'): d, s_, vt = f'Presidential margin_rd in {c[-4:]}.', 'county_election', c[-4:]
        else: d, s_, vt = c.replace('_', ' '), SRC[k][0], SRC[k][1]
        prov = 'derived' if (s_.startswith('derived') or c in ('nonmetro_2023', 'other_votes', 'pop_change_pct_decade', 'pop_change_2020_2024_pct', 'persons_per_senator', 'persons_per_house_seat', 'electoral_votes', 'pop_share', 'peak_pop')) else 'observed'
        if 'SAIPE' in s_ or 'Population Estimates' in s_: prov = 'observed (model-based estimate)'
        doc(k, c, d, s_, vt, prov)
pd.DataFrame(cb).to_csv(f'{OUT}/codebook.csv', index=False)
print(json.dumps({k: list(v.shape) for k, v in tabs.items()}), 'hospital_county_match', round(hosp_match, 4))
