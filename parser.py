import os
import unicodedata
from collections import defaultdict
from biothings_client import get_client
import requests
import re
# create symbolic link of myvariant.info repo first
from myvariant.src.utils.hgvs import get_hgvs_from_vcf
from csv import DictReader
from biothings.utils.dataload import dict_sweep, open_anyfile, unlist, value_convert_to_number


CHROM_LIST = [str(i) for i in range(1, 23)] + ['x', 'y']

"""
def get_hgvs_from_vcf(chr, pos, ref, alt, mutant_type=None):
    '''get a valid hgvs name from VCF-style "chr, pos, ref, alt" data.'''
    if not (re.match('^[ACGTN]+$', ref) and re.match('^[ACGTN*]+$', alt)):
        raise ValueError("Cannot convert {} into HGVS id.".format((chr, pos, ref, alt)))
    if len(ref) == len(alt) == 1:
        # this is a SNP
        hgvs = 'chr{0}:g.{1}{2}>{3}'.format(chr, pos, ref, alt)
        var_type = 'snp'
    elif len(ref) > 1 and len(alt) == 1:
        # this is a deletion:
        if ref[0] == alt:
            start = int(pos) + 1
            end = int(pos) + len(ref) - 1
            if start == end:
                hgvs = 'chr{0}:g.{1}del'.format(chr, start)
            else:
                hgvs = 'chr{0}:g.{1}_{2}del'.format(chr, start, end)
            var_type = 'del'
        else:
            end = int(pos) + len(ref) - 1
            hgvs = 'chr{0}:g.{1}_{2}delins{3}'.format(chr, pos, end, alt)
            var_type = 'delins'
    elif len(ref) == 1 and len(alt) > 1:
        # this is a insertion
        if alt[0] == ref:
            hgvs = 'chr{0}:g.{1}_{2}ins'.format(chr, pos, int(pos) + 1)
            ins_seq = alt[1:]
            hgvs += ins_seq
            var_type = 'ins'
        else:
            hgvs = 'chr{0}:g.{1}delins{2}'.format(chr, pos, alt)
            var_type = 'delins'
    elif len(ref) > 1 and len(alt) > 1:
        if ref[0] == alt[0]:
            # if ref and alt overlap from the left, trim them first
            _chr, _pos, _ref, _alt = _normalized_vcf(chr, pos, ref, alt)
            return get_hgvs_from_vcf(_chr, _pos, _ref, _alt, mutant_type=mutant_type)
        else:
            end = int(pos) + len(ref) - 1
            hgvs = 'chr{0}:g.{1}_{2}delins{3}'.format(chr, pos, end, alt)
            var_type = 'delins'
    else:
        raise ValueError("Cannot convert {} into HGVS id.".format((chr, pos, ref, alt)))
    if mutant_type:
        return hgvs, var_type
    else:
        return hgvs
"""


def batch_query_hgvs_from_rsid(rsid_list):
    hgvs_rsid_dict = {}
    print('total rsids: {}'.format(len(rsid_list)))
    rsid_list = list(set(rsid_list))
    variant_client = get_client('variant')
    for i in range(0, len(rsid_list), 1000):
        if i + 1000 <= len(rsid_list):
            batch = rsid_list[i: i+1000]
        else:
            batch = rsid_list[i:]
        params = ','.join(batch)
        res = variant_client.getvariants(params, fields="_id")
        print("currently processing {}th variant".format(i))
        for _doc in res:
            if '_id' not in _doc:
                print('can not convert', _doc)
            hgvs_rsid_dict[_doc['query']] = _doc['_id'] if '_id' in _doc else _doc["query"]
    return hgvs_rsid_dict


def str2float(item):
    """Convert string type to float type
    """
    if item == 'NR':
        return None
    elif item:
        try:
            return float(item)
        except ValueError:
            return None
    else:
        return None


def reorganize_field(field_value, seperator, num_snps):
    if 'non_coding_transcript_exon' in field_value:
        field_value = field_value.replace('exon', 'eXon')
    new_value = [_item.strip().replace('eXon', 'exon') for _item in field_value.split(seperator)]
    if num_snps == 1:
        return new_value
    else:

        if len(new_value) == num_snps:
            return new_value
        elif field_value == '':
            return [None] * num_snps
            # TODO: REST OF THE VALUES SHOULD BE SET TO none
        elif len(new_value) == 1:
            return new_value * num_snps
        elif len(new_value) < num_snps:
            new_value += [None] * (num_snps - len(new_value))
            return new_value
        else:
            print('new value', new_value, num_snps)


def load_data(data_folder):

    #input_file = os.path.join(data_folder, "alternative")
    input_file = os.path.join(data_folder, "gwas_catalog_v1.0.2-associations_e96_r2019-04-21.tsv")
    assert os.path.exists(input_file), "Can't find input file '%s'" % input_file
    with open_anyfile(input_file) as in_f:

        # Remove duplicated lines if any
        header = next(in_f).strip().split('\t')
        lines = set(list(in_f))
        reader = DictReader(lines, fieldnames=header, delimiter='\t')

        results = defaultdict(list)
        for row in reader:
            variant = {}

            # Use gDNA as variant identifier
            snps = []
            HGVS = False
            seperator = None
            if row["SNPS"].startswith("rs"):
                if "x" in row["SNPS"]:
                    snps = [_item.strip() for _item in row["SNPS"].split('x')]
                    seperator = "x"
                elif ";" in row["SNPS"]:
                    snps = [_item.strip() for _item in row["SNPS"].split(';')]
                    seperator = ";"
                elif row["SNPS"]:
                    snps = [row["SNPS"]]
            else:
                row["SNPS"] = row["SNPS"].replace('_', ":").replace('-', ':').split(':')
                if len(row["SNPS"]) == 4:
                    HGVS = True
                    chrom, pos, ref, alt = row["SNPS"]
                    chrom = str(chrom).replace('chr', '')
                    try:
                        snps = [get_hgvs_from_vcf(chrom, pos, ref, alt)]
                    except ValueError:
                        print(row["SNPS"])
                        continue
                else:
                    print(row["SNPS"])
                    continue
            region = reorganize_field(row["REGION"], seperator, len(snps))
            chrom = reorganize_field(row["CHR_ID"], seperator, len(snps))
            genes = reorganize_field(row["REPORTED GENE(S)"],
                                     seperator,
                                     len(snps))
            position = reorganize_field(row["CHR_POS"],
                                        seperator,
                                        len(snps))
            context = reorganize_field(row["CONTEXT"],
                                       seperator,
                                       len(snps))
            for i, _snp in enumerate(snps):
                variant = {}
                variant["_id"] = _snp
                variant['gwascatalog'] = {"associations": {'efo': {}, 'study': {}}}
                if not HGVS:
                    variant["gwascatalog"]["rsid"] = _snp
                variant['gwascatalog']['associations']['snps'] = snps
                variant['gwascatalog']['associations']['pubmed'] = int(row['PUBMEDID'])
                variant['gwascatalog']['associations']['date_added'] = row['DATE ADDED TO CATALOG']
                variant['gwascatalog']['associations']['study']['name'] = row['STUDY']
                variant['gwascatalog']['associations']['trait'] = row['DISEASE/TRAIT']
                variant['gwascatalog']['region'] = region[i] if region else None
                if not chrom:
                    chrom = [''] * 10 
                elif str(chrom[i]).lower() not in CHROM_LIST:
                    chrom[i] = ''
                variant['gwascatalog']['chrom'] = chrom[i] if chrom else None
                variant['gwascatalog']['pos'] = position[i] if position else None
                variant['gwascatalog']['gene'] = genes[i].split(',') if (genes and genes[i]) else None
                variant['gwascatalog']['context'] = context[i] if context else None
                variant['gwascatalog']['associations']['raf'] = str2float(row['RISK ALLELE FREQUENCY'])
                variant['gwascatalog']['associations']['pval'] = str2float(row['P-VALUE'])
                # variant['gwascatalog']['p_val_mlog'] = str2float(row['PVALUE_MLOG'])
                variant['gwascatalog']['associations']['study']['platform'] = row['PLATFORM [SNPS PASSING QC]']
                variant['gwascatalog']['associations']['study']['accession'] = row['STUDY ACCESSION']
                variant['gwascatalog']['associations']['efo']['name'] = row['MAPPED_TRAIT'].split(',')
                variant['gwascatalog']['associations']['efo']['id'] = [_item.split('/')[-1].replace('_', ':') for _item in row['MAPPED_TRAIT_URI'].split(',')]
                variant = dict_sweep(unlist(value_convert_to_number(variant, skipped_keys=['chrom'])), vals=[[], {}, None, '', 'NR'])
                results[variant["_id"]].append(variant)
        # Merge duplications
        rsid_list = [_item for _item in results.keys()]
        hgvs_rsid_dict = batch_query_hgvs_from_rsid(rsid_list)
        for v in results.values():
            if v[0]["_id"] in hgvs_rsid_dict and hgvs_rsid_dict[v[0]["_id"]]:
                if len(v) == 1:
                    v[0]["_id"] = hgvs_rsid_dict[v[0]["_id"]]
                    yield v[0]
                else:
                    doc = {'_id': hgvs_rsid_dict[v[0]['_id']],
                           'gwascatalog': {'associations': []}}
                    for _item in ['gene', 'region', 'pos', 'context', 'rsid']:
                        if _item in v[0]['gwascatalog']:
                            doc['gwascatalog'][_item] = v[0]['gwascatalog'][_item]
                    doc['gwascatalog']['associations'] = [i['gwascatalog']['associations'] for i in v]
                    yield doc