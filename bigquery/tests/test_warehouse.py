import importlib.util
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from economic_bq.core import collect
from economic_bq.warehouse import APP, Config, Warehouse

try:
    AVAILABLE=importlib.util.find_spec('google.cloud.bigquery') is not None
except ModuleNotFoundError:
    AVAILABLE=False


@unittest.skipUnless(AVAILABLE,'Instale requirements.txt para validar as configurações do SDK')
class WarehouseTests(unittest.TestCase):
    def test_foreign_dataset_is_not_adopted(self):
        client=Mock()
        client.get_dataset.return_value=SimpleNamespace(labels={},location='US')
        with self.assertRaises(ValueError):Warehouse(Config('example-project'),client).bootstrap()
        client.create_dataset.assert_not_called()

    def test_foreign_table_is_never_overwritten(self):
        client=Mock()
        client.get_dataset.return_value=SimpleNamespace(labels={'app':APP},location='US')
        client.get_table.return_value=SimpleNamespace(labels={'app':'unrelated'},table_type='TABLE')
        with self.assertRaises(ValueError):Warehouse(Config('example-project',mode='fixture'),client).load(collect(mode='fixture'),'test')
        client.load_table_from_json.assert_not_called()

    def test_wrong_provenance_is_never_loaded(self):
        client=Mock()
        with self.assertRaises(ValueError):Warehouse(Config('example-project',mode='live'),client).load(collect(mode='fixture'),'test')
        client.load_table_from_json.assert_not_called()

    def test_batch_load_uses_partition_clustering_and_strict_schema(self):
        from google.cloud import bigquery
        from google.api_core.exceptions import NotFound
        config=Config('example-project',mode='fixture')
        client=Mock()
        client.get_dataset.return_value=SimpleNamespace(labels={'app':APP},location='US')
        table=bigquery.Table(config.dataset('bronze')+'.observations')
        client.get_table.side_effect=[NotFound('missing'),table]
        job=client.load_table_from_json.return_value
        job.output_rows=75
        job.job_id='load-job'
        job.input_file_bytes=1234
        result=Warehouse(config,client).load(collect(mode='fixture'),'test')
        args=client.load_table_from_json.call_args
        load_config=args.kwargs['job_config']
        self.assertEqual(load_config.write_disposition,'WRITE_TRUNCATE')
        self.assertEqual(load_config.time_partitioning.field,'ingestion_date')
        self.assertEqual(load_config.clustering_fields,['source','indicator','reference_date'])
        self.assertEqual(load_config.max_bad_records,0)
        self.assertEqual(result['output_rows'],75)
        self.assertTrue(table.require_partition_filter)

    def test_query_sets_a_real_cost_cap(self):
        client=Mock()
        client.query.return_value.result.return_value=[]
        client.query.return_value.job_id='query-job'
        client.query.return_value.total_bytes_processed=100
        client.query.return_value.total_bytes_billed=0
        Warehouse(Config('example-project',maximum_bytes_billed=12345),client).query_latest()
        self.assertEqual(client.query.call_args.kwargs['job_config'].maximum_bytes_billed,12345)
        self.assertIn('example-project.portfolio_econ_live_gold',client.query.call_args.args[0])
