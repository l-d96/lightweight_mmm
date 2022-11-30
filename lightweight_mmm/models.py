# Copyright 2022 Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Module containing the different models available in the lightweightMMM lib.

Currently this file contains a main model with three possible options for
processing the media data. Which essentially grants the possibility of building
three different models.
  - Adstock
  - Hill-Adstock
  - Carryover
"""
import sys
#  pylint: disable=g-import-not-at-top
if sys.version_info >= (3, 8):
  from typing import Protocol
else:
  from typing_extensions import Protocol

from typing import Any, Dict, Mapping, MutableMapping, Optional, Sequence, Union

import immutabledict
import jax.numpy as jnp
import numpyro
from numpyro import distributions as dist

from lightweight_mmm import media_transforms

Prior = Union[
    dist.Distribution,
    Dict[str, float],
    Sequence[float],
    float
]


class TransformFunction(Protocol):

  def __call__(
      self,
      media_data: jnp.ndarray,
      custom_priors: MutableMapping[str, Prior],
      **kwargs: Any) -> jnp.ndarray:
    ...


_INTERCEPT = "intercept"
_COEF_TREND = "coef_trend"
_SIGMA = "sigma"
_COEF_EXTRA_FEATURES = "coef_extra_features"

MODEL_PRIORS_NAMES = frozenset((
    _INTERCEPT,
    _COEF_TREND,
    _SIGMA,
    _COEF_EXTRA_FEATURES))

_EXPONENT = "exponent"
_LAG_WEIGHT = "lag_weight"
_HALF_MAX_EFFECTIVE_CONCENTRATION = "half_max_effective_concentration"
_SLOPE = "slope"
_AD_EFFECT_RETENTION_RATE = "ad_effect_retention_rate"
_PEAK_EFFECT_DELAY = "peak_effect_delay"

TRANSFORM_PRIORS_NAMES = immutabledict.immutabledict({
    "carryover":
        frozenset((_AD_EFFECT_RETENTION_RATE, _PEAK_EFFECT_DELAY, _EXPONENT)),
    "adstock":
        frozenset((_EXPONENT, _LAG_WEIGHT)),
    "hill_adstock":
        frozenset((_LAG_WEIGHT, _HALF_MAX_EFFECTIVE_CONCENTRATION, _SLOPE)),
    "exponential_adstock":
        frozenset((_LAG_WEIGHT, _SLOPE)),
    "exponential_adstock_static_dim":
        frozenset((_LAG_WEIGHT, _SLOPE)),
    "exponential_adstock_static_decay":
        frozenset((_LAG_WEIGHT, _SLOPE)),
    "exponential_adstock_static_dim_decay":
        frozenset((_LAG_WEIGHT, _SLOPE))
})


def _get_default_priors() -> Mapping[str, Prior]:
  # Since JAX cannot be called before absl.app.run in tests we get default
  # priors from a function.
  return immutabledict.immutabledict({
      _INTERCEPT: dist.HalfNormal(scale=2.),
      _COEF_TREND: dist.Normal(loc=0., scale=1.),
      _SIGMA: dist.Gamma(concentration=1., rate=1.),
      _COEF_EXTRA_FEATURES: dist.Normal(loc=0., scale=1.),
  })


def _get_transform_default_priors() -> Mapping[str, Prior]:
  # Since JAX cannot be called before absl.app.run in tests we get default
  # priors from a function.
  return immutabledict.immutabledict({
      "carryover":
          immutabledict.immutabledict({
              _AD_EFFECT_RETENTION_RATE:
                  dist.Beta(concentration1=1., concentration0=1.),
              _PEAK_EFFECT_DELAY:
                  dist.HalfNormal(scale=2.),
              _EXPONENT:
                  dist.Beta(concentration1=9., concentration0=1.)
          }),
      "adstock":
          immutabledict.immutabledict({
              _EXPONENT: dist.Beta(concentration1=9., concentration0=1.),
              _LAG_WEIGHT: dist.Beta(concentration1=2., concentration0=1.)
          }),
      "hill_adstock":
          immutabledict.immutabledict({
              _LAG_WEIGHT:
                  dist.Beta(concentration1=2., concentration0=1.),
              _HALF_MAX_EFFECTIVE_CONCENTRATION:
                  dist.Gamma(concentration=1., rate=1.),
              _SLOPE:
                  dist.Gamma(concentration=1., rate=1.)
          }),
      "exponential_adstock":
          immutabledict.immutabledict({
              _LAG_WEIGHT:
                  dist.Beta(concentration1=2., concentration0=1.),
              _SLOPE:
                  dist.Gamma(concentration=1., rate=1.)
          }),
      "exponential_adstock_static_dim":
          immutabledict.immutabledict({
              _LAG_WEIGHT:
                  dist.Beta(concentration1=2., concentration0=1.),
          }),
      "exponential_adstock_static_decay":
          immutabledict.immutabledict({
              _SLOPE:
                  dist.Gamma(concentration=1., rate=1.)
          }),
      "exponential_adstock_static_dim_decay":
          immutabledict.immutabledict({
          })
  })


def transform_adstock(media_data: jnp.ndarray,
                      custom_priors: MutableMapping[str, Prior],
                      normalise: bool = True) -> jnp.ndarray:
  """Transforms the input data with the adstock function and exponent.

  Args:
    media_data: Media data to be transformed. It is expected to have 2 dims for
      national models and 3 for geo models.
    custom_priors: The custom priors we want the model to take instead of the
      default ones. The possible names of parameters for adstock and exponent
      are "lag_weight" and "exponent".
    normalise: Whether to normalise the output values.

  Returns:
    The transformed media data.
  """
  transform_default_priors = _get_transform_default_priors()["adstock"]
  with numpyro.plate(name=f"{_LAG_WEIGHT}_plate",
                     size=media_data.shape[1]):
    lag_weight = numpyro.sample(
        name=_LAG_WEIGHT,
        fn=custom_priors.get(_LAG_WEIGHT,
                             transform_default_priors[_LAG_WEIGHT]))

  with numpyro.plate(name=f"{_EXPONENT}_plate",
                     size=media_data.shape[1]):
    exponent = numpyro.sample(
        name=_EXPONENT,
        fn=custom_priors.get(_EXPONENT,
                             transform_default_priors[_EXPONENT]))

  if media_data.ndim == 3:
    lag_weight = jnp.expand_dims(lag_weight, axis=-1)
    exponent = jnp.expand_dims(exponent, axis=-1)

  adstock = media_transforms.adstock(
      data=media_data, lag_weight=lag_weight, normalise=normalise)

  return media_transforms.apply_exponent_safe(data=adstock, exponent=exponent)


def transform_hill_adstock(media_data: jnp.ndarray,
                           custom_priors: MutableMapping[str, Prior],
                           normalise: bool = True) -> jnp.ndarray:
  """Transforms the input data with the adstock and hill functions.

  Args:
    media_data: Media data to be transformed. It is expected to have 2 dims for
      national models and 3 for geo models.
    custom_priors: The custom priors we want the model to take instead of the
      default ones. The possible names of parameters for hill_adstock and
      exponent are "lag_weight", "half_max_effective_concentration" and "slope".
    normalise: Whether to normalise the output values.

  Returns:
    The transformed media data.
  """
  transform_default_priors = _get_transform_default_priors()["hill_adstock"]
  with numpyro.plate(name=f"{_LAG_WEIGHT}_plate",
                     size=media_data.shape[1]):
    lag_weight = numpyro.sample(
        name=_LAG_WEIGHT,
        fn=custom_priors.get(_LAG_WEIGHT,
                             transform_default_priors[_LAG_WEIGHT]))

  with numpyro.plate(name=f"{_HALF_MAX_EFFECTIVE_CONCENTRATION}_plate",
                     size=media_data.shape[1]):
    half_max_effective_concentration = numpyro.sample(
        name=_HALF_MAX_EFFECTIVE_CONCENTRATION,
        fn=custom_priors.get(
            _HALF_MAX_EFFECTIVE_CONCENTRATION,
            transform_default_priors[_HALF_MAX_EFFECTIVE_CONCENTRATION]))

  with numpyro.plate(name=f"{_SLOPE}_plate",
                     size=media_data.shape[1]):
    slope = numpyro.sample(
        name=_SLOPE,
        fn=custom_priors.get(_SLOPE, transform_default_priors[_SLOPE]))

  if media_data.ndim == 3:
    lag_weight = jnp.expand_dims(lag_weight, axis=-1)
    half_max_effective_concentration = jnp.expand_dims(
        half_max_effective_concentration, axis=-1)
    slope = jnp.expand_dims(slope, axis=-1)

  return media_transforms.hill(
      data=media_transforms.adstock(
          data=media_data, lag_weight=lag_weight, normalise=normalise),
      half_max_effective_concentration=half_max_effective_concentration,
      slope=slope)

def transform_exponential_adstock(media_data: jnp.ndarray,
                           custom_priors: MutableMapping[str, Prior],
                           normalise: bool = False) -> jnp.ndarray:
  """Transforms the input data with the adstock and hill functions.

  Args:
    media_data: Media data to be transformed. It is expected to have 2 dims for
      national models and 3 for geo models.
    custom_priors: The custom priors we want the model to take instead of the
      default ones. The possible names of parameters for hill_adstock and
      exponent are "lag_weight", "half_max_effective_concentration" and "slope".
    normalise: Whether to normalise the output values.

  Returns:
    The transformed media data.
  """
  transform_default_priors = _get_transform_default_priors()["exponential_adstock"]
  with numpyro.plate(name=f"{_LAG_WEIGHT}_plate",
                     size=media_data.shape[1]):
    lag_weight = numpyro.sample(
        name=_LAG_WEIGHT,
        fn=custom_priors.get(_LAG_WEIGHT,
                             transform_default_priors[_LAG_WEIGHT]))

  with numpyro.plate(name=f"{_SLOPE}_plate",
                     size=media_data.shape[1]):
    slope = numpyro.sample(
        name=_SLOPE,
        fn=custom_priors.get(_SLOPE, transform_default_priors[_SLOPE]))

  if media_data.ndim == 3:
    lag_weight = jnp.expand_dims(lag_weight, axis=-1)
    slope = jnp.expand_dims(slope, axis=-1)

  return media_transforms.exponential(
      data=media_transforms.adstock(
          data=media_data, lag_weight=lag_weight, normalise=normalise),
      slope=slope)

def transform_exponential_adstock_static_dim(media_data: jnp.ndarray,
                           custom_priors: MutableMapping[str, Prior],
                           normalise: bool = False) -> jnp.ndarray:
  """Transforms the input data with the adstock and hill functions.

  Args:
    media_data: Media data to be transformed. It is expected to have 2 dims for
      national models and 3 for geo models.
    custom_priors: The custom priors we want the model to take instead of the
      default ones. The possible names of parameters for hill_adstock and
      exponent are "lag_weight", "half_max_effective_concentration" and "slope".
    normalise: Whether to normalise the output values.

  Returns:
    The transformed media data.
  """
  transform_default_priors = _get_transform_default_priors()["exponential_adstock_static_dim"]
  with numpyro.plate(name=f"{_LAG_WEIGHT}_plate",
                     size=media_data.shape[1]):
    lag_weight = numpyro.sample(
        name=_LAG_WEIGHT,
        fn=custom_priors.get(_LAG_WEIGHT,
                             transform_default_priors[_LAG_WEIGHT]))
  slope = custom_priors.get(_SLOPE, 1)

  if media_data.ndim == 3:
    lag_weight = jnp.expand_dims(lag_weight, axis=-1)
    slope = jnp.expand_dims(slope, axis=-1)

  return media_transforms.exponential(
      data=media_transforms.adstock(
          data=media_data, lag_weight=lag_weight, normalise=normalise),
      slope=slope)

def transform_exponential_adstock_static_decay(media_data: jnp.ndarray,
                           custom_priors: MutableMapping[str, Prior],
                           normalise: bool = False) -> jnp.ndarray:
  """Transforms the input data with the adstock and hill functions.

  Args:
    media_data: Media data to be transformed. It is expected to have 2 dims for
      national models and 3 for geo models.
    custom_priors: The custom priors we want the model to take instead of the
      default ones. The possible names of parameters for hill_adstock and
      exponent are "lag_weight", "half_max_effective_concentration" and "slope".
    normalise: Whether to normalise the output values.

  Returns:
    The transformed media data.
  """
  transform_default_priors = _get_transform_default_priors()["exponential_adstock_static_decay"]
  lag_weight = custom_priors.get(_LAG_WEIGHT, 1)

  with numpyro.plate(name=f"{_SLOPE}_plate",
                     size=media_data.shape[1]):
    slope = numpyro.sample(
        name=_SLOPE,
        fn=custom_priors.get(_SLOPE, transform_default_priors[_SLOPE]))

  if media_data.ndim == 3:
    lag_weight = jnp.expand_dims(lag_weight, axis=-1)
    slope = jnp.expand_dims(slope, axis=-1)

  return media_transforms.exponential(
      data=media_transforms.adstock(
          data=media_data, lag_weight=lag_weight, normalise=normalise),
      slope=slope)

def transform_exponential_adstock_static_dim_decay(media_data: jnp.ndarray,
                           custom_priors: MutableMapping[str, Prior],
                           normalise: bool = False) -> jnp.ndarray:
  """Transforms the input data with the adstock and hill functions.

  Args:
    media_data: Media data to be transformed. It is expected to have 2 dims for
      national models and 3 for geo models.
    custom_priors: The custom priors we want the model to take instead of the
      default ones. The possible names of parameters for hill_adstock and
      exponent are "lag_weight", "half_max_effective_concentration" and "slope".
    normalise: Whether to normalise the output values.

  Returns:
    The transformed media data.
  """
  transform_default_priors = _get_transform_default_priors()["exponential_adstock_static_dim_decay"]
  lag_weight = custom_priors.get(_LAG_WEIGHT, 1)
  slope = custom_priors.get(_SLOPE, 1)

  if media_data.ndim == 3:
    lag_weight = jnp.expand_dims(lag_weight, axis=-1)
    slope = jnp.expand_dims(slope, axis=-1)

  return media_transforms.exponential(
      data=media_transforms.adstock(
          data=media_data, lag_weight=lag_weight, normalise=normalise),
      slope=slope)

def transform_carryover(media_data: jnp.ndarray,
                        custom_priors: MutableMapping[str, Prior],
                        number_lags: int = 13) -> jnp.ndarray:
  """Transforms the input data with the carryover function and exponent.

  Args:
    media_data: Media data to be transformed. It is expected to have 2 dims for
      national models and 3 for geo models.
    custom_priors: The custom priors we want the model to take instead of the
      default ones. The possible names of parameters for carryover and exponent
      are "ad_effect_retention_rate_plate", "peak_effect_delay_plate" and
      "exponent".
    number_lags: Number of lags for the carryover function.

  Returns:
    The transformed media data.
  """
  transform_default_priors = _get_transform_default_priors()["carryover"]
  with numpyro.plate(name=f"{_AD_EFFECT_RETENTION_RATE}_plate",
                     size=media_data.shape[1]):
    ad_effect_retention_rate = numpyro.sample(
        name=_AD_EFFECT_RETENTION_RATE,
        fn=custom_priors.get(
            _AD_EFFECT_RETENTION_RATE,
            transform_default_priors[_AD_EFFECT_RETENTION_RATE]))

  with numpyro.plate(name=f"{_PEAK_EFFECT_DELAY}_plate",
                     size=media_data.shape[1]):
    peak_effect_delay = numpyro.sample(
        name=_PEAK_EFFECT_DELAY,
        fn=custom_priors.get(
            _PEAK_EFFECT_DELAY, transform_default_priors[_PEAK_EFFECT_DELAY]))

  with numpyro.plate(name=f"{_EXPONENT}_plate",
                     size=media_data.shape[1]):
    exponent = numpyro.sample(
        name=_EXPONENT,
        fn=custom_priors.get(_EXPONENT,
                             transform_default_priors[_EXPONENT]))
  carryover = media_transforms.carryover(
      data=media_data,
      ad_effect_retention_rate=ad_effect_retention_rate,
      peak_effect_delay=peak_effect_delay,
      number_lags=number_lags)

  if media_data.ndim == 3:
    exponent = jnp.expand_dims(exponent, axis=-1)
  return media_transforms.apply_exponent_safe(data=carryover, exponent=exponent)


def media_mix_model(
    media_data: jnp.ndarray,
    target_data: jnp.ndarray,
    media_prior: jnp.ndarray,
    media_sigma: jnp.ndarray,
    transform_function: TransformFunction,
    custom_priors: MutableMapping[str, Prior],
    transform_kwargs: Optional[MutableMapping[str, Any]] = None,
    extra_features: Optional[jnp.array] = None
    ) -> None:
  """Media mix model.

  Args:
    media_data: Media data to be be used in the model.
    target_data: Target data for the model.
    media_prior: Cost prior for each of the media channels.
    degrees_seasonality: Number of degrees of seasonality to use.
    frequency: Frequency of the time span which was used to aggregate the data.
      Eg. if weekly data then frequency is 52.
    transform_function: Function to use to transform the media data in the
      model. Currently the following are supported: 'transform_adstock',
        'transform_carryover' and 'transform_hill_adstock'.
    custom_priors: The custom priors we want the model to take instead of the
      default ones. See our custom_priors documentation for details about the
      API and possible options.
    transform_kwargs: Any extra keyword arguments to pass to the transform
      function. For example the adstock function can take a boolean to noramlise
      output or not.
    weekday_seasonality: In case of daily data you can estimate a weekday (7)
      parameter.
    extra_features: Extra features data to include in the model.
  """
  default_priors = _get_default_priors()
  data_size = media_data.shape[0]
  n_channels = media_data.shape[1]
  geo_shape = (media_data.shape[2],) if media_data.ndim == 3 else ()
  n_geos = media_data.shape[2] if media_data.ndim == 3 else 1

  with numpyro.plate(name=f"{_INTERCEPT}_plate", size=n_geos):
    intercept = numpyro.sample(
        name=_INTERCEPT,
        fn=custom_priors.get(_INTERCEPT, default_priors[_INTERCEPT]))

  with numpyro.plate(name=f"{_SIGMA}_plate", size=n_geos):
    sigma = numpyro.sample(
        name=_SIGMA,
        fn=custom_priors.get(_SIGMA, default_priors[_SIGMA]))

  with numpyro.plate(
      name="channel_media_plate",
      size=n_channels,
      dim=-2 if media_data.ndim == 3 else -1):
    coef_media = numpyro.sample(
        name="channel_coef_media" if media_data.ndim == 3 else "coef_media",
        fn=dist.Normal(loc=media_prior, scale=media_sigma))
    if media_data.ndim == 3:
      with numpyro.plate(
          name="geo_media_plate",
          size=n_geos,
          dim=-1):
        coef_media = numpyro.sample(
            name="coef_media", fn=dist.Normal(loc=media_prior, scale=media_sigma))

  media_transformed = numpyro.deterministic(
      name="media_transformed",
      value=transform_function(media_data,
                               custom_priors=custom_priors,
                               **transform_kwargs if transform_kwargs else {}))

  # For national models
  media_einsum = "tc, c -> t"  # t = time, c = channel
  prediction = (
      intercept + jnp.einsum(media_einsum, media_transformed, coef_media))
  if extra_features is not None:
    plate_prefixes = ("extra_feature",)
    extra_features_einsum = "tf, f -> t"  # t = time, f = feature
    extra_features_plates_shape = (extra_features.shape[1],)
    if extra_features.ndim == 3:
      plate_prefixes = ("extra_feature", "geo")
      extra_features_einsum = "tfg, fg -> tg"  # t = time, f = feature, g = geo
      extra_features_plates_shape = (extra_features.shape[1], *geo_shape)
    with numpyro.plate_stack(plate_prefixes,
                             sizes=extra_features_plates_shape):
      coef_extra_features = numpyro.sample(
          name=_COEF_EXTRA_FEATURES,
          fn=custom_priors.get(
              _COEF_EXTRA_FEATURES, default_priors[_COEF_EXTRA_FEATURES]))
    extra_features_effect = jnp.einsum(extra_features_einsum,
                                       extra_features,
                                       coef_extra_features)
    prediction += extra_features_effect

  mu = numpyro.deterministic(name="mu", value=prediction)

  numpyro.sample(
      name="target", fn=dist.Normal(loc=mu, scale=sigma), obs=target_data)
