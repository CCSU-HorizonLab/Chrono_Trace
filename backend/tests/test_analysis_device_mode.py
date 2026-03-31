import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile


backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))


from app.services.analysis.feature_extraction_config import FeatureExtractionConfig
from app.services.analysis.preprocessing_orchestrator import PreprocessingOrchestrator
from app.services.analysis.sentiment_service import SentimentService
from app.services.realtime.realtime_sentiment_service import RealtimeSentimentService
from app.webview.bridge import Bridge


def reset_sentiment_services():
    sentiment_service = SentimentService()
    sentiment_service._embedding_model = None
    sentiment_service._embedding_load_failed = False
    sentiment_service._embedding_device = "cpu"
    sentiment_service.configure_device_mode("auto")
    if sentiment_service._realtime_service is not None:
        sentiment_service._realtime_service._model = None
        sentiment_service._realtime_service._tokenizer = None
        sentiment_service._realtime_service._device = "cpu"
        sentiment_service._realtime_service.configure_device_mode("auto")


class TestAnalysisDeviceMode:
    def teardown_method(self):
        reset_sentiment_services()

    def test_realtime_service_cpu_mode_ignores_cuda(self):
        service = RealtimeSentimentService(skip_db_init=True)
        service.configure_device_mode("cpu")

        fake_model = MagicMock()
        fake_model.config.num_labels = 3
        fake_model.to = MagicMock(return_value=fake_model)
        fake_model.eval = MagicMock()

        with patch("app.services.realtime.realtime_sentiment_service.AutoTokenizer.from_pretrained", return_value=object()), \
             patch("app.services.realtime.realtime_sentiment_service.AutoModelForSequenceClassification.from_pretrained", return_value=fake_model), \
             patch("app.services.realtime.realtime_sentiment_service.torch.cuda.is_available", return_value=True), \
             patch.object(service._model_manager, "ensure_model_exists", return_value=True):
            service._model = None
            service._tokenizer = None
            service._load_model()

        fake_model.to.assert_not_called()
        assert service._device == "cpu"

    def test_realtime_service_gpu_mode_uses_cuda_when_available(self):
        service = RealtimeSentimentService(skip_db_init=True)
        service.configure_device_mode("gpu")

        fake_model = MagicMock()
        fake_model.config.num_labels = 3
        fake_model.to = MagicMock(return_value=fake_model)
        fake_model.eval = MagicMock()

        with patch("app.services.realtime.realtime_sentiment_service.AutoTokenizer.from_pretrained", return_value=object()), \
             patch("app.services.realtime.realtime_sentiment_service.AutoModelForSequenceClassification.from_pretrained", return_value=fake_model), \
             patch("app.services.realtime.realtime_sentiment_service.torch.cuda.is_available", return_value=True), \
             patch("app.services.realtime.realtime_sentiment_service.torch.cuda.get_device_name", return_value="Fake GPU"), \
             patch.object(service._model_manager, "ensure_model_exists", return_value=True):
            service._model = None
            service._tokenizer = None
            service._load_model()

        fake_model.to.assert_called_once_with("cuda")
        assert service._device == "cuda"

    def test_sentiment_service_mode_switch_resets_cached_models(self):
        service = SentimentService()
        realtime_service = RealtimeSentimentService(skip_db_init=True)
        service._embedding_model = object()
        service._embedding_model_path = "cached-path"
        service._realtime_service = realtime_service
        realtime_service._model = object()
        realtime_service._tokenizer = object()

        service.configure_device_mode("cpu")

        assert service._embedding_model is None
        assert service._embedding_model_path is None
        assert realtime_service._model is None
        assert realtime_service._tokenizer is None
        assert service._device_mode == "cpu"

    def test_sentiment_service_loads_embedding_from_local_path_only(self):
        service = SentimentService()
        service._embedding_model = None
        service._embedding_load_failed = False

        fake_model = MagicMock()

        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(service, "_resolve_local_embedding_model_path", return_value=temp_dir), \
             patch("sentence_transformers.SentenceTransformer", return_value=fake_model) as mock_sentence_transformer:
            service._load_embedding_model()

        mock_sentence_transformer.assert_called_once()
        assert mock_sentence_transformer.call_args.args[0] == temp_dir
        assert mock_sentence_transformer.call_args.kwargs["local_files_only"] is True

    def test_sentiment_service_skips_embedding_load_without_local_model(self):
        service = SentimentService()
        service._embedding_model = None
        service._embedding_load_failed = False

        with patch.object(service, "_resolve_local_embedding_model_path", return_value=None), \
             patch("sentence_transformers.SentenceTransformer") as mock_sentence_transformer:
            service._load_embedding_model()

        assert service._embedding_load_failed is True
        mock_sentence_transformer.assert_not_called()

    def test_bridge_settings_and_extract_features_override(self):
        with patch("app.webview.bridge.WeChatIngestService", return_value=MagicMock()), \
             patch("app.services.realtime.floating_window_service.FloatingWindowService", return_value=MagicMock()):
            bridge = Bridge()
        bridge.settings_file = backend_root / "tests" / "_tmp_analysis_device_settings.json"
        bridge.settings = {}
        try:
            saved = bridge.set_settings({"analysis_device_mode": "GPU"})
            assert saved["payload"]["analysis_device_mode"] == "gpu"
            assert bridge.get_settings()["analysis_device_mode"] == "gpu"

            fake_service = MagicMock()
            fake_service.config = FeatureExtractionConfig()
            fake_service.extract_features.return_value = {"task_id": "t1"}
            bridge._feature_service = fake_service
            result = bridge.extract_features(42, {"analysis_device_mode": "cpu"})

            assert result["success"] is True
            assert fake_service.extract_features.called
            assert fake_service.config.analysis_device_mode == "cpu"
        finally:
            if bridge.settings_file.exists():
                bridge.settings_file.unlink()

    def test_preprocessing_orchestrator_uses_batch_cache_path(self):
        orchestrator = PreprocessingOrchestrator()
        orchestrator.sentiment_service.batch_get_sentiment_from_cache = MagicMock(return_value={1: {"polarity": 1}})
        orchestrator.sentiment_service.analyze_batch = MagicMock(return_value=[{"polarity": 0, "intensity": 0.0, "embedding": [0.0] * 384}])
        orchestrator.sentiment_service.batch_cache_sentiments = MagicMock()

        messages = [
            {"id": 1, "message_type": 1, "content": "cached"},
            {"id": 2, "message_type": 1, "content": "miss"},
        ]

        orchestrator._ensure_sentiment_analysis(123, messages)

        orchestrator.sentiment_service.batch_get_sentiment_from_cache.assert_called_once_with([1, 2])
        orchestrator.sentiment_service.analyze_batch.assert_called_once_with(["miss"])
        orchestrator.sentiment_service.batch_cache_sentiments.assert_called_once()

    def test_preprocessing_orchestrator_uses_session_initiator_stats(self):
        orchestrator = PreprocessingOrchestrator()
        orchestrator._load_messages = MagicMock(return_value=[
            {"id": 1, "message_type": 1, "content": "hello", "is_sender": 1, "timestamp": 1},
        ])
        orchestrator._ensure_sentiment_analysis = MagicMock()
        orchestrator.basic_service.collect_message_statistics = MagicMock(return_value={})
        orchestrator.basic_service.collect_time_statistics = MagicMock(return_value={})
        orchestrator.basic_service.collect_length_statistics = MagicMock(return_value={})
        orchestrator.pair_service.build_speech_units = MagicMock(return_value=[{"id": 1}])
        orchestrator.pair_service.build_interaction_pairs = MagicMock(return_value=[])
        orchestrator.pair_service.clear_cached_pairs = MagicMock()
        orchestrator.pair_service.save_speech_units_with_mapping = MagicMock(return_value={})
        orchestrator.pair_service.save_interaction_pairs = MagicMock()
        orchestrator.pair_service.collect_pair_statistics = MagicMock(return_value={})
        orchestrator.session_manager.split_sessions = MagicMock(return_value=[{"initiator_is_sender": 0}])
        orchestrator.session_manager.save_sessions = MagicMock()
        orchestrator.session_manager.collect_session_statistics = MagicMock(return_value={
            "total_sessions": 3,
            "average_session_length": 2.5,
            "average_session_gap": 42.0,
        })
        orchestrator.session_manager.identify_session_initiators = MagicMock(return_value={
            "sender_initiated_count": 1,
            "contact_initiated_count": 2,
        })
        orchestrator.attitude_service.collect_attitude_statistics = MagicMock(return_value=MagicMock())

        stats = orchestrator._collect_all_statistics(123)

        assert stats.total_sessions == 3
        assert stats.sender_initiated_count == 1
        assert stats.contact_initiated_count == 2
        orchestrator.session_manager.identify_session_initiators.assert_called_once()
