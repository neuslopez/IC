import sys
import numpy as np

from .. core.core_functions    import weighted_mean_and_var
from .. core.system_of_units_c import units
from .. core.exceptions        import SipmEmptyList
from .. core.exceptions        import SipmZeroCharge
from .. core.exceptions        import SipmEmptyListAboveQthr
from .. core.exceptions        import SipmZeroChargeAboveQthr
from .. core.exceptions        import ClusterEmptyList

from .. types.ic_types         import xy
from .. evm.event_model        import Cluster

from .. core.system_of_units_c import units

from itertools import product


def find_algorithm(algoname):
    if algoname in sys.modules[__name__].__dict__:
        return getattr(sys.modules[__name__], algoname)
    else:
        raise ValueError("The algorithm <{}> does not exist".format(algoname))


def barycenter(pos, qs):
    """pos = column np.array --> (matrix n x 2)
       ([x1, y1],
        [x2, y2]
        ...
        [xs, ys])
       qs = vector (q1, q2...qs) --> (1xn)

        """

    if not len(pos)   : raise SipmEmptyList
    if np.sum(qs) == 0: raise SipmZeroCharge
    mu, var = weighted_mean_and_var(pos, qs, axis=0)
    # For uniformity of interface, all xy algorithms should return a
    # list of clusters. barycenter always returns a single clusters,
    # but we still want it in a list.
    return [Cluster(np.sum(qs), xy(*mu), xy(*var), len(qs))]

    #return [Cluster(sum(qs), XY(*mu), var, len(qs))]


def discard_sipms(sis, pos, qs):
    return np.delete(pos, sis, axis=0), np.delete(qs, sis)


def get_nearby_sipm_inds(cs, d, pos, qs):
    """return indices of sipms less than d from (xc,yc)"""
    return np.where(np.linalg.norm(pos - cs, axis=1) <= d)[0]


def get_neighbours(cs, pitch):
    """return positions of all sipms around cs,
       irrespectively of the charge detected"""
    x0, y0 = cs[0]
    shift = np.array([-pitch, 0, +pitch])
    return product(x0 + shift, y0 + shift)


def have_same_position_in_space(a, b):
    return np.allclose(a, b)


def is_masked(sipm, masked_sipm):
    return any(have_same_position_in_space(sipm, m_sipm)
                   for m_sipm in masked_sipm)


def corona(pos, qs,
           Qthr           =  0 * units.pes,
           Qlm            =  5 * units.pes,
           lm_radius      =  0 * units.mm,
           new_lm_radius  = 15 * units.mm,
           msipm          =  3,
           pitch          = 10. * units.mm,
           masked_sipm    = ()):
    """
    corona creates a list of Clusters by
    first , identifying hottest_sipm, the sipm with max charge in qs (must be > Qlm)
    second, calling barycenter() on the pos and qs SiPMs within lm_radius of hottest_sipm to
            find new_local_maximum.
    third , calling barycenter() on all SiPMs within new_lm_radius of new_local_maximum
    fourth, recording the Cluster found by barycenter if the cluster contains at least msipm
    fifth , removing (nondestructively) the sipms contributing to that Cluster
    sixth , repeating 1-5 until there are no more SiPMs of charge > Qlm

    arguments:
    pos   = column np.array --> (matrix n x 2)
            ([x1, y1],
             [x2, y2],
             ...     ,
             [xs, ys])
    qs    = vector (q1, q2...qs) --> (1xn)
    Qthr  = charge threshold, ignore all SiPMs with less than Qthr pes
    Qlm   = charge threshold, every Cluster must contain at least one SiPM with charge >= Qlm
    msipm = minimum number of SiPMs in a Cluster
    pitch = distance between SiPMs
    lm_radius = radius, find new_local_maximum by taking the barycenter of SiPMs within
                lm_radius of the max sipm. new_local_maximum is new in the sense that the
                prev loc max was the position of hottest_sipm. (Then allow all SiPMs with
                new_local_maximum of new_local_maximum to contribute to the pos and q of the
                new cluster).

                ***In general lm_radius should typically be set to 0, or some value slightly
                larger than pitch or pitch*sqrt(2).***

                ***If lm_radius is set to a negative number, the algorithm will simply return
                the overall barycenter all the SiPms above threshold.***


                ---------
                    This kwarg has some physical motivation. It exists to try to partially
                compensate problem that the NEW tracking plane is not continuous even though light
                can be emitted by the EL at any (x,y). When lm_radius < pitch, the search for SiPMs
                that might contribute pos and charge to a new Cluster is always centered about
                the position of hottest_sipm. That is, SiPMs within new_lm_radius of
                hottest_sipm are taken into account by barycenter(). In contrast, when
                lm_radius = pitch or pitch*sqrt(2) the search for SiPMs contributing to the new
                cluster can be centered at any (x,y). Consider the case where at a local maximum
                there are four nearly equally 'hot' SiPMs. new_local_maximum would yield a pos,
                pos1, between these hot SiPMs. Searching for SiPMs that contribute to this
                cluster within new_lm_radius of pos1 might be better than searching searching for
                SiPMs  within new_lm_radius of hottest_sipm.
                    We should be aware that setting lm_radius to some distance greater than pitch,
                we allow new_local_maximum to assume any (x,y) but we also create the effect that
                depending on where new_local_maximum is, more or fewer SiPMs will be
                within new_lm_radius. This effect does not exist when lm_radius = 0
                    lm_radius can always be set to 0 mm, but setting it to 15 mm (slightly larger
                than 10mm * sqrt(2)), should not hurt.

    new_lm_radius = radius, find a new cluster by calling barycenter() on pos/qs of SiPMs within
                    new_lm_radius of new_local_maximum

    masked_sipm = list of positions of masked SiPMs

    returns
    c    : a list of Clusters

    Usage Example
    In order to create each Cluster from a 3x3 block of SiPMs (where the center SiPM has more
    charge than the others), one would call:
    corona(pos, qs,
           Qthr           =  K1 * units.pes,
           Qlm            =  K2 * units.pes,
           lm_radius      =  0  * units.mm , # must be 0
           new_lm_radius  =  15 * units.mm , # must be 10mm*sqrt(2) or some number slightly larger
           msipm          =  K3)
    """

    if not len(pos)   : raise SipmEmptyList
    if np.sum(qs) == 0: raise SipmZeroCharge

    above_threshold = np.where(qs >= Qthr)[0]            # Find SiPMs with qs at least Qthr
    pos, qs = pos[above_threshold], qs[above_threshold]  # Discard SiPMs with qs less than Qthr

    if not len(pos)   : raise SipmEmptyListAboveQthr
    if np.sum(qs) == 0: raise SipmZeroChargeAboveQthr

    # if lm_radius or new_lm_radius is negative, just call overall barycenter
    if lm_radius < 0 or new_lm_radius < 0:
        return barycenter(pos, qs)

    c  = []
    # While there are more local maxima
    while len(qs) > 0:

        hottest_sipm = np.argmax(qs)       # SiPM with largest Q
        if qs[hottest_sipm] < Qlm: break   # largest Q remaining is negligible

        # find new local maximum of charge considering all SiPMs within lm_radius of hottest_sipm
        within_lm_radius   = get_nearby_sipm_inds(pos[hottest_sipm], lm_radius, pos, qs)
        new_local_maximum  = barycenter(pos[within_lm_radius], qs[within_lm_radius])[0].posxy

        # find the SiPMs within new_lm_radius of the new local maximum of charge
        within_new_lm_radius = get_nearby_sipm_inds(new_local_maximum, new_lm_radius, pos, qs)

        # find any masked channel in the first ring around the new local maximum of charge
        neighbours = get_neighbours(new_local_maximum, pitch)

        n_masked_neighbours = sum(1 for neigh in neighbours if is_masked(neigh, masked_sipm))

        # if there are at least msipms within_new_lm_radius, taking
        # into account any masked channel, get the barycenter
        if len(within_new_lm_radius) >= msipm - n_masked_neighbours:
            c.extend(barycenter(pos[within_new_lm_radius], qs[within_new_lm_radius]))

        # delete the SiPMs contributing to this cluster
        pos, qs = discard_sipms(within_new_lm_radius, pos, qs)

    if not len(c): raise ClusterEmptyList

    return c
