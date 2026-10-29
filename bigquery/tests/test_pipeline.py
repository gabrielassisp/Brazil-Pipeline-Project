import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from economic_bq.core import (QualityError, collect, fetch_json, number, observation,
                              parse_bcb, parse_ibge, parse_worldbank, validate_rows, validate_window)
from economic_bq.warehouse import Config
from economic_bq.__main__ import main


class CoreTests(unittest.TestCase):
    def test_non_finite_missing_and_boolean_rejected(self):
        for value in [None, True, float('nan'), float('inf'), 'NaN', '...', '-inf']:
            with self.subTest(value=value), self.assertRaises(QualityError):
                number(value)
        self.assertEqual(number('1,25'),1.25)

    def test_ibge_types_period_and_locality(self):
        data=[{},dict(D1C='1',D2C='63',D3C='202401',V='0.42')]
        row=parse_ibge(data)[0]
        self.assertEqual((row['reference_date'],row['frequency'],row['value']),('2024-01-01','monthly',.42))
        data[1]['D1C']='35'
        with self.assertRaises(QualityError):parse_ibge(data)

    def test_bcb_uses_latest_daily_observation_not_average(self):
        rows=parse_bcb([dict(data='31/01/2024',valor='11.25'),dict(data='01/01/2024',valor='11.75')])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['value'],11.25)

    def test_worldbank_preserves_annual_frequency_and_skips_null(self):
        rows=[dict(countryiso3code='BRA',indicator={'id':'NY.GDP.MKTP.KD.ZG'},date='2024',value=3.4),
              dict(countryiso3code='BRA',indicator={'id':'NY.GDP.MKTP.KD.ZG'},date='2023',value=None)]
        result=parse_worldbank([{'pages':1},rows])
        self.assertEqual((len(result),result[0]['frequency'],result[0]['reference_date']),(1,'annual','2024-01-01'))
        with self.assertRaises(QualityError):parse_worldbank([{'pages':2},rows])

    def test_empty_sources_fail(self):
        for parser,payload in [(parse_ibge,[]),(parse_bcb,[]),(parse_worldbank,[{'pages':1},[]])]:
            with self.assertRaises(QualityError):parser(payload)

    def test_fixture_has_explicit_provenance_and_stable_business_keys(self):
        first=collect(mode='fixture')
        second=collect(mode='fixture')
        self.assertEqual(len(first),75)
        self.assertEqual({r['observation_key'] for r in first},{r['observation_key'] for r in second})
        self.assertTrue(all(r['is_synthetic'] for r in first))
        self.assertTrue(all(r['ingestion_date'] == r['ingested_at'][:10] for r in first))
        self.assertEqual(len({r['ingestion_date'] for r in first}), 1)
        self.assertEqual({r['source'] for r in first},{'ibge','bcb','worldbank'})

    def test_live_failure_never_returns_fixture(self):
        with self.assertRaises(URLError):
            collect(getter=Mock(side_effect=URLError('offline')))

    def test_duplicates_or_missing_source_block_publication(self):
        rows=collect(mode='fixture')
        with self.assertRaises(QualityError):validate_rows(rows+[rows[0]])
        with self.assertRaises(QualityError):validate_rows([r for r in rows if r['source']!='ibge'])

    def test_invalid_window_rejected(self):
        for start,end in [('2024-02-02','2024-12-31'),('2024-01-01','2024-02-15'),('2010-01-01','2024-12-31')]:
            with self.assertRaises(QualityError):validate_window(start,end)

    def test_transient_http_retry_but_not_permanent_http_errors(self):
        opener=Mock(side_effect=[HTTPError('https://example.com',503,'busy',{},None),io.BytesIO(b'{"ok":true}')])
        sleep=Mock()
        self.assertEqual(fetch_json('https://example.com',opener=opener,sleep=sleep),{'ok':True})
        sleep.assert_called_once_with(1)
        opener=Mock(side_effect=HTTPError('https://example.com',400,'bad request',{},None))
        with self.assertRaises(HTTPError):fetch_json('https://example.com',opener=opener,sleep=sleep)
        self.assertEqual(opener.call_count,1)

    def test_invalid_json_not_disguised_as_data(self):
        with self.assertRaises(ValueError):fetch_json('https://example.com',opener=lambda *a,**k:io.BytesIO(b'broken'))

    def test_extraction_cli_writes_only_local_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            main(['extract','--mode','fixture','--output',tmp])
            report=json.loads(next(Path(tmp).glob('*/run.json')).read_text())
            self.assertEqual((report['status'],report['row_count']),('extracted_only',75))
            self.assertNotIn('load',report)


class ConfigTests(unittest.TestCase):
    def test_project_must_be_explicit(self):
        with self.assertRaises(ValueError):Config('')

    def test_fixture_and_live_are_separate_destinations(self):
        live=Config('example-project',mode='live')
        fixture=Config('example-project',mode='fixture')
        self.assertNotEqual(live.dataset('bronze'),fixture.dataset('bronze'))

    def test_sql_identifiers_and_query_cap_validated(self):
        for kwargs in [dict(prefix='bad`; drop'),dict(maximum_bytes_billed=0),dict(mode='bad')]:
            with self.assertRaises(ValueError):Config('example-project',**kwargs)


if __name__=='__main__':unittest.main()
