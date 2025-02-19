# -*- coding: utf-8 -*-
#
# Copyright 2017-2019 Spotify AB.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#

import logging
import os
import time
from os.path import join as pjoin
from typing import List, Optional  # noqa: F401

import tensorflow_data_validation as tfdv
from tensorflow_data_validation.statistics.stats_options import StatsOptions
from apache_beam.options.pipeline_options import GoogleCloudOptions, PipelineOptions, SetupOptions
from tensorflow_metadata.proto.v0.statistics_pb2 import DatasetFeatureStatisticsList  # noqa: F401
from spotify_tensorflow.tfx.utils import create_setup_file, assert_not_empty_string, \
    clean_up_pipeline_args
from spotify_tensorflow.tf_schema_utils import parse_schema_txt_file, parse_schema_file
from tensorflow_metadata.proto.v0 import statistics_pb2  # noqa: F401
from tensorflow.python.lib.io import file_io

logger = logging.getLogger("spotify-tensorflow")


class TfDataValidator(object):
    """Spotify-specific API for using Tensorflow Data Valiation in production.

    The typical usage is to create an instance of this class from a Luigi task that produces
    tfrecord files in order to produce statistics, a schema snapshot and any anomalies along with
    the dataset.
    """

    def __init__(self,
                 schema_path,                   # type: Optional[str]
                 data_location,                 # type: str
                 binary_schema=False,           # type: bool
                 stats_options=StatsOptions()   # type: StatsOptions
                 ):
        """
        :param schema_path: tf.metadata Schema path. Must be in text or binary format. If this is
                            None, a new schema will be inferred automatically from the statistics.
        :param data_location: input data dir containing tfrecord files
        :param binary_schema: specifies if the schema is in a binary format
        """
        self.data_location = data_location
        self.schema = None
        if schema_path:
            if binary_schema:
                self.schema = parse_schema_file(schema_path)
            else:
                self.schema = parse_schema_txt_file(schema_path)
        self.schema_snapshot_path = pjoin(self.data_location, "schema_snapshot.pb")
        self.stats_path = pjoin(self.data_location, "stats.pb")
        self.anomalies_path = pjoin(self.data_location, "anomalies.pb")
        self.stats_options = stats_options

    def write_stats(self, pipeline_args):
        # type: (List[str]) -> statistics_pb2.DatasetFeatureStatisticsList
        return generate_statistics_from_tfrecord(pipeline_args=pipeline_args,
                                                 data_location=self.data_location,
                                                 output_path=self.stats_path,
                                                 stats_options=self.stats_options)

    def write_stats_and_schema(self,
                               pipeline_args,
                               infer_feature_shape=False
                               ):
        # type: (List[str], bool) -> None
        stats = self.write_stats(pipeline_args)
        if not self.schema:
            logger.warning(
                "Inferring a new schema for this dataset. If you want to use an existing schema, "
                "provide a value for schema_path in the constructor."
            )
            new_schema = tfdv.infer_schema(stats, infer_feature_shape=infer_feature_shape)
            self.schema = new_schema
        self.upload_schema()

    def validate_stats_against_schema(self,
                                      environment=None,
                                      previous_statistics=None,
                                      serving_statistics=None,
                                      ):
        # type: (str, DatasetFeatureStatisticsList, DatasetFeatureStatisticsList) -> bool
        stats = tfdv.load_statistics(self.stats_path)
        self.anomalies = tfdv.validate_statistics(
            stats,
            self.schema,
            environment=environment,
            previous_statistics=previous_statistics,
            serving_statistics=serving_statistics,
        )
        if len(self.anomalies.anomaly_info.items()) > 0:
            logger.error("Anomalies found in training dataset...")
            logger.error(str(self.anomalies.anomaly_info.items()))
            self.upload_anomalies()
            return False
        else:
            logger.info("No anomalies found")
            return True

    def upload_schema(self):  # type: () -> None
        if not self.schema:
            raise ValueError(
                "Cannot upload a schema since no schema_path was provided. Either provide one, or "
                "use write_stats_and_schema so that a schema can be inferred first."
            )
        file_io.atomic_write_string_to_file(self.schema_snapshot_path,
                                            self.schema.SerializeToString())

    def upload_anomalies(self):  # type: () -> None
        if self.anomalies.anomaly_info:
            file_io.atomic_write_string_to_file(self.anomalies_path,
                                                self.anomalies.SerializeToString())


def generate_statistics_from_tfrecord(pipeline_args,  # type: List[str]
                                      data_location,  # type: str
                                      output_path,    # type: str
                                      stats_options   # type: StatsOptions
                                      ):
    # type: (...) ->  statistics_pb2.DatasetFeatureStatisticsList
    """
    Generate stats file from a tfrecord dataset using TFDV

    :param pipeline_args: un-parsed Dataflow arguments
    :param data_location: input data dir containing tfrecord files
    :param output_path: output path for the stats file
    :return a DatasetFeatureStatisticsList proto.
    """
    assert_not_empty_string(data_location)
    assert_not_empty_string(output_path)

    args_in_snake_case = clean_up_pipeline_args(pipeline_args)
    pipeline_options = PipelineOptions(flags=args_in_snake_case)

    all_options = pipeline_options.get_all_options()

    if all_options["job_name"] is None:
        gcloud_options = pipeline_options.view_as(GoogleCloudOptions)
        gcloud_options.job_name = "generatestats-%s" % str(time.time())[:-3]

    if all_options["setup_file"] is None:
        setup_file_path = create_setup_file()
        setup_options = pipeline_options.view_as(SetupOptions)
        setup_options.setup_file = setup_file_path

    input_files = os.path.join(data_location, "*.tfrecords*")
    return tfdv.generate_statistics_from_tfrecord(data_location=input_files,
                                                  output_path=output_path,
                                                  stats_options=stats_options,
                                                  pipeline_options=pipeline_options)
