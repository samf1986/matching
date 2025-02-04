""" The HR game class and supporting functions. """
import copy
import warnings

from matching import BaseGame, MultipleMatching
from matching import Player as Resident
from matching.algorithms import hospital_resident
from matching.exceptions import (
    MatchingError,
    PlayerExcludedWarning,
    PreferencesChangedWarning,
)
from matching.players import Hospital


class HospitalResident(BaseGame):
    """A class for solving instances of the hospital-resident assignment
    problem (HR).

    In this case, a blocking pair is any resident-hospital pair that satisfies
    **all** of the following:

        - They are present in each other's preference lists;
        - either the resident is unmatched, or they prefer the hospital to their
          current match;
        - either the hospital is under-subscribed, or they prefer the resident
          to at least one of their current matches.

    Parameters
    ----------
    residents : list of Player
        The residents in the matching game. Each resident must rank a subset of
        those in :code:`hospitals`.
    hospitals : list of Hospital
        The hospitals in the matching game. Each hospital must rank all of (and
        only) the residents which rank it.
    clean : bool
        Indicator for whether the players of the game should be cleaned.
        Cleaning is reductive in nature, removing players from the game and/or
        other player's preferences if they do not meet the requirements of the
        game.

    Attributes
    ----------
    matching : Matching or None
        Once the game is solved, a matching is available as a :code:`Matching`
        object with the hospitals as keys and their resident matches as values.
        Initialises as :code:`None`.
    blocking_pairs : list of (Player, Hospital) or None
        Initialises as `None`. Otherwise, a list of the resident-hospital
        blocking pairs.
    """

    def __init__(self, residents, hospitals, clean=False):

        residents, hospitals = copy.deepcopy([residents, hospitals])
        self.residents = residents
        self.hospitals = hospitals
        self.clean = clean

        self._all_residents = residents
        self._all_hospitals = hospitals

        super().__init__(clean)
        self.check_inputs()

    @classmethod
    def create_from_dictionaries(
        cls, resident_prefs, hospital_prefs, capacities, clean=False
    ):
        """Create an instance of :code:`HospitalResident` from two preference
        dictionaries and capacities. If :code:`clean=True` then remove players
        from the game and/or player preferences if they do not satisfy the
        conditions of the game."""

        residents, hospitals = _make_players(
            resident_prefs, hospital_prefs, capacities
        )
        game = cls(residents, hospitals, clean)
        return game

    def solve(self, optimal="resident"):
        """Solve the instance of HR using either the resident- or
        hospital-oriented algorithm. Return the matching."""

        self.matching = MultipleMatching(
            hospital_resident(self.residents, self.hospitals, optimal)
        )
        return self.matching

    def check_validity(self):
        """ Check whether the current matching is valid. """

        unacceptable_issues = self._check_for_unacceptable_matches(
            "residents"
        ) + self._check_for_unacceptable_matches("hospitals")

        oversubscribed_issues = self._check_for_oversubscribed_players(
            "hospitals"
        )

        if unacceptable_issues or oversubscribed_issues:
            raise MatchingError(
                unacceptable_matches=unacceptable_issues,
                oversubscribed_hospitals=oversubscribed_issues,
            )

        return True

    def _check_for_unacceptable_matches(self, party):
        """Check that no player in `party` is matched to an unacceptable
        player."""

        issues = []
        for player in vars(self)[party]:
            issue = player.check_if_match_is_unacceptable(unmatched_okay=True)
            if isinstance(issue, list):
                issues.extend(issue)
            elif isinstance(issue, str):
                issues.append(issue)

        return issues

    def _check_for_oversubscribed_players(self, party):
        """ Check that no player in `party` is oversubscribed. """

        issues = []
        for player in vars(self)[party]:
            issue = player.check_if_oversubscribed()
            if issue:
                issues.append(issue)

        return issues

    def check_stability(self):
        """Check for the existence of any blocking pairs in the current
        matching, thus determining the stability of the matching."""

        blocking_pairs = []
        for resident in self.residents:
            for hospital in self.hospitals:
                if (
                    _check_mutual_preference(resident, hospital)
                    and _check_resident_unhappy(resident, hospital)
                    and _check_hospital_unhappy(resident, hospital)
                ):
                    blocking_pairs.append((resident, hospital))

        self.blocking_pairs = blocking_pairs
        return not any(blocking_pairs)

    def check_inputs(self):
        """Give out warnings if any of the conditions of the game have been
        broken. If the :code:`clean` attribute is :code:`True`, then remove any
        such situations from the game."""

        self._check_inputs_player_prefs_unique("residents")
        self._check_inputs_player_prefs_unique("hospitals")

        self._check_inputs_player_prefs_all_in_party("residents", "hospitals")
        self._check_inputs_player_prefs_all_in_party("hospitals", "residents")

        self._check_inputs_player_prefs_all_reciprocated("hospitals")
        self._check_inputs_player_reciprocated_all_prefs(
            "hospitals", "residents"
        )

        self._check_inputs_player_prefs_nonempty("residents", "hospitals")
        self._check_inputs_player_prefs_nonempty("hospitals", "residents")

        self._check_inputs_player_capacity("hospitals", "residents")

    def _check_inputs_player_prefs_all_reciprocated(self, party):
        """Make sure that each player in :code:`party` has ranked only those
        players that have ranked it."""

        for player in vars(self)[party]:

            for other in player.prefs:
                if player not in other.prefs:
                    warnings.warn(
                        PreferencesChangedWarning(
                            f"{player} ranked {other} but they did not."
                        )
                    )
                    if self.clean:
                        player._forget(other)

    def _check_inputs_player_reciprocated_all_prefs(self, party, other_party):
        """Make sure that each player in :code:`party` has ranked all those
        players in :code:`other_party` that have ranked it."""

        players = vars(self)[party]
        others = vars(self)[other_party]
        for player in players:

            others_that_ranked = [
                other for other in others if player in other.prefs
            ]
            for other in others_that_ranked:
                if other not in player.prefs:
                    warnings.warn(
                        PreferencesChangedWarning(
                            f"{other} ranked {player} but they did not."
                        )
                    )
                    if self.clean:
                        other._forget(player)

    def _check_inputs_player_capacity(self, party, other_party):
        """Check that each player in :code:`party` has a capacity of at least
        one. If the :code:`clean` attribute is :code:`True`, remove any hospital
        that does not have such a capacity from the game."""

        for player in vars(self)[party]:
            if player.capacity < 1:
                warnings.warn(PlayerExcludedWarning(player))

                if self.clean:
                    self._remove_player(player, party, other_party)


def _check_mutual_preference(resident, hospital):
    """ Determine whether two players each have a preference of the other. """

    return resident in hospital.prefs and hospital in resident.prefs


def _check_resident_unhappy(resident, hospital):
    """Determine whether a resident is unhappy because they are unmatched, or
    they prefer the hospital to their current match."""

    return resident.matching is None or resident.prefers(
        hospital, resident.matching
    )


def _check_hospital_unhappy(resident, hospital):
    """Determine whether a hospital is unhappy because they are
    under-subscribed, or they prefer the resident to at least one of their
    current matches."""

    return len(hospital.matching) < hospital.capacity or any(
        [hospital.prefers(resident, match) for match in hospital.matching]
    )


def _make_players(resident_prefs, hospital_prefs, capacities):
    """Make a set of residents and hospitals from the dictionaries given, and
    add their preferences."""

    resident_dict, hospital_dict = _make_instances(
        resident_prefs, hospital_prefs, capacities
    )

    for resident_name, resident in resident_dict.items():
        prefs = [hospital_dict[name] for name in resident_prefs[resident_name]]
        resident.set_prefs(prefs)

    for hospital_name, hospital in hospital_dict.items():
        prefs = [resident_dict[name] for name in hospital_prefs[hospital_name]]
        hospital.set_prefs(prefs)

    residents = list(resident_dict.values())
    hospitals = list(hospital_dict.values())

    return residents, hospitals


def _make_instances(resident_prefs, hospital_prefs, capacities):
    """Create ``Player`` (resident) and ``Hospital`` instances for the names in
    each dictionary."""

    resident_dict, hospital_dict = {}, {}
    for resident_name in resident_prefs:
        resident = Resident(name=resident_name)
        resident_dict[resident_name] = resident
    for hospital_name in hospital_prefs:
        capacity = capacities[hospital_name]
        hospital = Hospital(name=hospital_name, capacity=capacity)
        hospital_dict[hospital_name] = hospital

    return resident_dict, hospital_dict
