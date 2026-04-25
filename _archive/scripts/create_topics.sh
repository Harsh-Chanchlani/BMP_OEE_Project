#!/usr/bin/env bash
confluent kafka topic create OEE_0       --partitions 5 --if-not-exists
confluent kafka topic create OEE_0_DLQ   --partitions 1 --if-not-exists
confluent kafka topic create OEE_ALERTS  --partitions 1 --if-not-exists
