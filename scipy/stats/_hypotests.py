from collections import namedtuple
import numpy as np
import warnings
from scipy.special import gamma, kv, gammaln
from scipy.fft import ifft
from . import distributions
from ._continuous_distns import chi2


Epps_Singleton_2sampResult = namedtuple('Epps_Singleton_2sampResult',
                                        ('statistic', 'pvalue'))


def epps_singleton_2samp(x, y, t=(0.4, 0.8)):
    """
    Compute the Epps-Singleton (ES) test statistic.

    Test the null hypothesis that two samples have the same underlying
    probability distribution.

    Parameters
    ----------
    x, y : array-like
        The two samples of observations to be tested. Input must not have more
        than one dimension. Samples can have different lengths.
    t : array-like, optional
        The points (t1, ..., tn) where the empirical characteristic function is
        to be evaluated. It should be positive distinct numbers. The default
        value (0.4, 0.8) is proposed in [1]_. Input must not have more than
        one dimension.

    Returns
    -------
    statistic : float
        The test statistic.
    pvalue : float
        The associated p-value based on the asymptotic chi2-distribution.

    See Also
    --------
    ks_2samp, anderson_ksamp

    Notes
    -----
    Testing whether two samples are generated by the same underlying
    distribution is a classical question in statistics. A widely used test is
    the Kolmogorov-Smirnov (KS) test which relies on the empirical
    distribution function. Epps and Singleton introduce a test based on the
    empirical characteristic function in [1]_.

    One advantage of the ES test compared to the KS test is that is does
    not assume a continuous distribution. In [1]_, the authors conclude
    that the test also has a higher power than the KS test in many
    examples. They recommend the use of the ES test for discrete samples as
    well as continuous samples with at least 25 observations each, whereas
    `anderson_ksamp` is recommended for smaller sample sizes in the
    continuous case.

    The p-value is computed from the asymptotic distribution of the test
    statistic which follows a `chi2` distribution. If the sample size of both
    `x` and `y` is below 25, the small sample correction proposed in [1]_ is
    applied to the test statistic.

    The default values of `t` are determined in [1]_ by considering
    various distributions and finding good values that lead to a high power
    of the test in general. Table III in [1]_ gives the optimal values for
    the distributions tested in that study. The values of `t` are scaled by
    the semi-interquartile range in the implementation, see [1]_.

    References
    ----------
    .. [1] T. W. Epps and K. J. Singleton, "An omnibus test for the two-sample
       problem using the empirical characteristic function", Journal of
       Statistical Computation and Simulation 26, p. 177--203, 1986.

    .. [2] S. J. Goerg and J. Kaiser, "Nonparametric testing of distributions
       - the Epps-Singleton two-sample test using the empirical characteristic
       function", The Stata Journal 9(3), p. 454--465, 2009.

    """

    x, y, t = np.asarray(x), np.asarray(y), np.asarray(t)
    # check if x and y are valid inputs
    if x.ndim > 1:
        raise ValueError('x must be 1d, but x.ndim equals {}.'.format(x.ndim))
    if y.ndim > 1:
        raise ValueError('y must be 1d, but y.ndim equals {}.'.format(y.ndim))
    nx, ny = len(x), len(y)
    if (nx < 5) or (ny < 5):
        raise ValueError('x and y should have at least 5 elements, but len(x) '
                         '= {} and len(y) = {}.'.format(nx, ny))
    if not np.isfinite(x).all():
        raise ValueError('x must not contain nonfinite values.')
    if not np.isfinite(y).all():
        raise ValueError('y must not contain nonfinite values.')
    n = nx + ny

    # check if t is valid
    if t.ndim > 1:
        raise ValueError('t must be 1d, but t.ndim equals {}.'.format(t.ndim))
    if np.less_equal(t, 0).any():
        raise ValueError('t must contain positive elements only.')

    # rescale t with semi-iqr as proposed in [1]; import iqr here to avoid
    # circular import
    from scipy.stats import iqr
    sigma = iqr(np.hstack((x, y))) / 2
    ts = np.reshape(t, (-1, 1)) / sigma

    # covariance estimation of ES test
    gx = np.vstack((np.cos(ts*x), np.sin(ts*x))).T  # shape = (nx, 2*len(t))
    gy = np.vstack((np.cos(ts*y), np.sin(ts*y))).T
    cov_x = np.cov(gx.T, bias=True)  # the test uses biased cov-estimate
    cov_y = np.cov(gy.T, bias=True)
    est_cov = (n/nx)*cov_x + (n/ny)*cov_y
    est_cov_inv = np.linalg.pinv(est_cov)
    r = np.linalg.matrix_rank(est_cov_inv)
    if r < 2*len(t):
        warnings.warn('Estimated covariance matrix does not have full rank. '
                      'This indicates a bad choice of the input t and the '
                      'test might not be consistent.')  # see p. 183 in [1]_

    # compute test statistic w distributed asympt. as chisquare with df=r
    g_diff = np.mean(gx, axis=0) - np.mean(gy, axis=0)
    w = n*np.dot(g_diff.T, np.dot(est_cov_inv, g_diff))

    # apply small-sample correction
    if (max(nx, ny) < 25):
        corr = 1.0/(1.0 + n**(-0.45) + 10.1*(nx**(-1.7) + ny**(-1.7)))
        w = corr * w

    p = chi2.sf(w, r)

    return Epps_Singleton_2sampResult(w, p)


class CramerVonMisesResult:
    def __init__(self, statistic, pvalue):
        self.statistic = statistic
        self.pvalue = pvalue

    def __repr__(self):
        return (f"{self.__class__.__name__}(statistic={self.statistic}, "
                f"pvalue={self.pvalue})")


def _psi1_mod(x):
    """
    psi1 is defined in equation 1.10 in Csorgo, S. and Faraway, J. (1996).
    This implements a modified version by excluding the term V(x) / 12
    (here: _cdf_cvm_inf(x) / 12) to avoid evaluating _cdf_cvm_inf(x)
    twice in _cdf_cvm.

    Implementation based on MAPLE code of Julian Faraway and R code of the
    function pCvM in the package goftest (v1.1.1), permission granted
    by Adrian Baddeley. Main difference in the implementation: the code
    here keeps adding terms of the series until the terms are small enough.
    """

    def _ed2(y):
        z = y**2 / 4
        b = kv(1/4, z) + kv(3/4, z)
        return np.exp(-z) * (y/2)**(3/2) * b / np.sqrt(np.pi)

    def _ed3(y):
        z = y**2 / 4
        c = np.exp(-z) / np.sqrt(np.pi)
        return c * (y/2)**(5/2) * (2*kv(1/4, z) + 3*kv(3/4, z) - kv(5/4, z))

    def _Ak(k, x):
        m = 2*k + 1
        sx = 2 * np.sqrt(x)
        y1 = x**(3/4)
        y2 = x**(5/4)

        e1 = m * gamma(k + 1/2) * _ed2((4 * k + 3)/sx) / (9 * y1)
        e2 = gamma(k + 1/2) * _ed3((4 * k + 1) / sx) / (72 * y2)
        e3 = 2 * (m + 2) * gamma(k + 3/2) * _ed3((4 * k + 5) / sx) / (12 * y2)
        e4 = 7 * m * gamma(k + 1/2) * _ed2((4 * k + 1) / sx) / (144 * y1)
        e5 = 7 * m * gamma(k + 1/2) * _ed2((4 * k + 5) / sx) / (144 * y1)

        return e1 + e2 + e3 + e4 + e5

    x = np.asarray(x)
    tot = np.zeros_like(x, dtype='float')
    cond = np.ones_like(x, dtype='bool')
    k = 0
    while np.any(cond):
        z = -_Ak(k, x[cond]) / (np.pi * gamma(k + 1))
        tot[cond] = tot[cond] + z
        cond[cond] = np.abs(z) >= 1e-7
        k += 1

    return tot


def _cdf_cvm_inf(x):
    """
    Calculate the cdf of the Cramér-von Mises statistic (infinite sample size).

    See equation 1.2 in Csorgo, S. and Faraway, J. (1996).

    Implementation based on MAPLE code of Julian Faraway and R code of the
    function pCvM in the package goftest (v1.1.1), permission granted
    by Adrian Baddeley. Main difference in the implementation: the code
    here keeps adding terms of the series until the terms are small enough.

    The function is not expected to be accurate for large values of x, say
    x > 4, when the cdf is very close to 1.
    """
    x = np.asarray(x)

    def term(x, k):
        # this expression can be found in [2], second line of (1.3)
        u = np.exp(gammaln(k + 0.5) - gammaln(k+1)) / (np.pi**1.5 * np.sqrt(x))
        y = 4*k + 1
        q = y**2 / (16*x)
        b = kv(0.25, q)
        return u * np.sqrt(y) * np.exp(-q) * b

    tot = np.zeros_like(x, dtype='float')
    cond = np.ones_like(x, dtype='bool')
    k = 0
    while np.any(cond):
        z = term(x[cond], k)
        tot[cond] = tot[cond] + z
        cond[cond] = np.abs(z) >= 1e-7
        k += 1

    return tot


def _cdf_cvm(x, n=None):
    """
    Calculate the cdf of the Cramér-von Mises statistic for a finite sample
    size n. If N is None, use the asymptotic cdf (n=inf)

    See equation 1.8 in Csorgo, S. and Faraway, J. (1996) for finite samples,
    1.2 for the asymptotic cdf.

    The function is not expected to be accurate for large values of x, say
    x > 2, when the cdf is very close to 1 and it might return values > 1
    in that case, e.g. _cdf_cvm(2.0, 12) = 1.0000027556716846.
    """
    x = np.asarray(x)
    if n is None:
        y = _cdf_cvm_inf(x)
    else:
        # support of the test statistic is [12/n, n/3], see 1.1 in [2]
        y = np.zeros_like(x, dtype='float')
        sup = (1./(12*n) < x) & (x < n/3.)
        # note: _psi1_mod does not include the term _cdf_cvm_inf(x) / 12
        # therefore, we need to add it here
        y[sup] = _cdf_cvm_inf(x[sup]) * (1 + 1./(12*n)) + _psi1_mod(x[sup]) / n
        y[x >= n/3] = 1

    if y.ndim == 0:
        return y[()]
    return y


def cramervonmises(rvs, cdf, args=()):
    """
    Perform the Cramér-von Mises test for goodness of fit.

    This performs a test of the goodness of fit of a cumulative distribution
    function (cdf) :math:`F` compared to the empirical distribution function
    :math:`F_n` of observed random variates :math:`X_1, ..., X_n` that are
    assumed to be independent and identically distributed ([1]_).
    The null hypothesis is that the :math:`X_i` have cumulative distribution
    :math:`F`.

    Parameters
    ----------
    rvs : array_like
        A 1-D array of observed values of the random variables :math:`X_i`.
    cdf : str or callable
        The cumulative distribution function :math:`F` to test the
        observations against. If a string, it should be the name of a
        distribution in `scipy.stats`. If a callable, that callable is used
        to calculate the cdf: ``cdf(x, *args) -> float``.
    args : tuple, optional
        Distribution parameters. These are assumed to be known; see Notes.

    Returns
    -------
    res : object with attributes
        statistic : float
            Cramér-von Mises statistic.
        pvalue :  float
            The p-value.

    See Also
    --------
    kstest

    Notes
    -----
    .. versionadded:: 1.6.0

    The p-value relies on the approximation given by equation 1.8 in [2]_.
    It is important to keep in mind that the p-value is only accurate if
    one tests a simple hypothesis, i.e. the parameters of the reference
    distribution are known. If the parameters are estimated from the data
    (composite hypothesis), the computed p-value is not reliable.

    References
    ----------
    .. [1] https://en.wikipedia.org/wiki/Cramér-von_Mises_criterion
    .. [2] Csorgo, S. and Faraway, J. (1996). The Exact and Asymptotic
           Distribution of Cramér-von Mises Statistics. Journal of the
           Royal Statistical Society, pp. 221-234.

    Examples
    --------

    Suppose we wish to test whether data generated by ``scipy.stats.norm.rvs``
    were, in fact, drawn from the standard normal distribution. We choose a
    significance level of alpha=0.05.

    >>> import numpy as np
    >>> from scipy import stats
    >>> np.random.seed(626)
    >>> x = stats.norm.rvs(size=500)
    >>> res = stats.cramervonmises(x, 'norm')
    >>> res.statistic, res.pvalue
    (0.06342154705518796, 0.792680516270629)

    The p-value 0.79 exceeds our chosen significance level, so we do not
    reject the null hypothesis that the observed sample is drawn from the
    standard normal distribution.

    Now suppose we wish to check whether the same sampels shifted by 2.1 is
    consistent with being drawn from a normal distribution with a mean of 2.

    >>> y = x + 2.1
    >>> res = stats.cramervonmises(y, 'norm', args=(2,))
    >>> res.statistic, res.pvalue
    (0.4798693195559657, 0.044782228803623814)

    Here we have used the `args` keyword to specify the mean (``loc``)
    of the normal distribution to test the data against. This is equivalent
    to the following, in which we create a frozen normal distribution with
    mean 2.1, then pass its ``cdf`` method as an argument.

    >>> frozen_dist = stats.norm(loc=2)
    >>> res = stats.cramervonmises(y, frozen_dist.cdf)
    >>> res.statistic, res.pvalue
    (0.4798693195559657, 0.044782228803623814)

    In either case, we would reject the null hypothesis that the observed
    sample is drawn from a normal distribution with a mean of 2 (and default
    variance of 1) because the p-value 0.04 is less than our chosen
    significance level.

    """
    if isinstance(cdf, str):
        cdf = getattr(distributions, cdf).cdf

    vals = np.sort(np.asarray(rvs))

    if vals.size <= 1:
        raise ValueError('The sample must contain at least two observations.')
    if vals.ndim > 1:
        raise ValueError('The sample must be one-dimensional.')

    n = len(vals)
    cdfvals = cdf(vals, *args)

    u = (2*np.arange(1, n+1) - 1)/(2*n)
    w = 1/(12*n) + np.sum((u - cdfvals)**2)

    # avoid small negative values that can occur due to the approximation
    p = max(0, 1. - _cdf_cvm(w, n))

    return CramerVonMisesResult(statistic=w, pvalue=p)


def _get_wilcoxon_distr(n):
    """
    Distribution of probability of the Wilcoxon ranksum statistic r_plus (sum
    of ranks of positive differences).
    Returns an array with the probabilities of all the possible ranks
    r = 0, ..., n*(n+1)/2
    """
    c = np.ones(1, dtype=np.double)
    for k in range(1, n + 1):
        prev_c = c
        c = np.zeros(k * (k + 1) // 2 + 1, dtype=np.double)
        m = len(prev_c)
        c[:m] = prev_c * 0.5
        c[-m:] += prev_c * 0.5
    return c


def _get_wilcoxon_distr2(n):
    """
    Distribution of probability of the Wilcoxon ranksum statistic r_plus (sum
    of ranks of positive differences).
    Returns an array with the probabilities of all the possible ranks
    r = 0, ..., n*(n+1)/2
    This is a slower reference function
    References
    ----------
    .. [1] 1. Harris T, Hardin JW. Exact Wilcoxon Signed-Rank and Wilcoxon
        Mann-Whitney Ranksum Tests. The Stata Journal. 2013;13(2):337-343.
    """
    ai = np.arange(1, n+1)[:, None]
    t = n*(n+1)/2
    q = 2*t
    j = np.arange(q)
    theta = 2*np.pi/q*j
    phi_sp = np.prod(np.cos(theta*ai), axis=0)
    phi_s = np.exp(1j*theta*t) * phi_sp
    p = np.real(ifft(phi_s))
    res = np.zeros(int(t)+1)
    res[:-1:] = p[::2]
    res[0] /= 2
    res[-1] = res[0]
    return res
