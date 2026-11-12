import sys, json, shapefile, pandas as pd
RAW, B = sys.argv[1], sys.argv[2]
P = [('20019','great_plains_farming','Farming-dependent, RUCC 9, population-loss county in KS/NE/SD/ND with a Critical Access Hospital; nearest the pool median population without overlapping another archetype.'),
     ('54047','appalachian_persistent_poverty','Persistent-poverty, mining-dependent county in KY/WV; nearest the pool median population.'),
     ('01131','black_belt_persistent_poverty','Persistent-poverty, majority-Black nonmetro county in AL/MS/AR/LA; nearest the pool median population.'),
     ('31173','tribal_lands','Nonmetro county outside Alaska with a Native American majority; nearest the pool median population. Tribal data sovereignty applies.'),
     ('16081','mountain_west_recreation','Recreation and retirement-destination nonmetro county in the Mountain West; chosen over the nearest-median county (Sierra NM, 4,181 sq mi) for tractable 3D extent and because it is at its population peak, the opposite trajectory to the other four.')]
m = pd.read_csv(f'{B}/data/county_master.csv', dtype={'fips5': str}); p = pd.read_csv(f'{B}/data/county_profile.csv', dtype={'fips5': str})
h = pd.read_csv(f'{B}/data/facility_hospital.csv', dtype=str)
sf = shapefile.Reader(f'{RAW}/tiger/cb_2023_us_county_500k')
geo = {r.record['GEOID']: r for r in sf.iterShapeRecords() if r.record['GEOID'] in [x[0] for x in P]}
rows, feats = [], []
keep = ['fips5','county_name','state_abbr','rucc_2023','land_area_sqmi','centroid_lat','centroid_lon','pop_1900_census','peak_pop_decade','peak_pop','pop_2020_census','pop_2024_estimate','pop_2020_pct_of_peak','census_rural_share_2020','housing_units_2020','pop_density_2020_per_sqmi','poverty_rate_2023','median_hh_income_2023','n_hospitals','n_critical_access_hospitals','n_rural_emergency_hospitals','pres_margin_rd_2016','pres_margin_rd_2020','pres_margin_rd_2024']
pk = ['Age65AndOlderPct2020','WhiteNonHispanicPct2020','BlackNonHispanicPct2020','HispanicPct2020','NativeAmericanNonHispanicPct2020','Ed5CollegePlusPct']
for f, arch, why in P:
    r = m[m.fips5 == f][keep].iloc[0].to_dict(); r.update(p[p.fips5 == f][pk].iloc[0].to_dict())
    bb = [round(v, 5) for v in geo[f].shape.bbox]
    r.update(archetype=arch, selection_rule=why, bbox_west=bb[0], bbox_south=bb[1], bbox_east=bb[2], bbox_north=bb[3],
             hospitals='; '.join((h[h.fips5 == f]['Facility Name'] + ' [' + h[h.fips5 == f]['Hospital Type'] + ']').tolist()))
    rows.append(r)
    feats.append({'type': 'Feature', 'properties': {'fips5': f, 'name': r['county_name'], 'state': r['state_abbr'], 'archetype': arch}, 'geometry': geo[f].shape.__geo_interface__})
d = pd.DataFrame(rows); d = d[['fips5','county_name','state_abbr','archetype','selection_rule'] + [c for c in d.columns if c not in ('fips5','county_name','state_abbr','archetype','selection_rule')]]
d.to_csv(f'{B}/pilots/pilot_counties.csv', index=False)
json.dump({'type': 'FeatureCollection', 'name': 'pilot_county_boundaries', 'crs_note': 'NAD83 (EPSG:4269), Census cartographic boundary 2023, 1:500k', 'features': feats}, open(f'{B}/pilots/pilot_county_boundaries.geojson', 'w'))
print(d.drop(columns=['selection_rule']).T.to_string())
