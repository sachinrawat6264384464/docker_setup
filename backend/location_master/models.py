from django.db import models


class Country(models.Model):
    """Master list of countries. India (IN) is seeded by default."""
    name = models.CharField(max_length=100, unique=True, db_index=True)
    code = models.CharField(max_length=3, unique=True)  # ISO 3166-1 alpha-2/3

    class Meta:
        verbose_name = 'Country'
        verbose_name_plural = 'Countries'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"


class State(models.Model):
    """Indian states and union territories."""
    country = models.ForeignKey(
        Country, on_delete=models.CASCADE, related_name='states'
    )
    name = models.CharField(max_length=100, db_index=True)
    code = models.CharField(max_length=10)  # e.g. 'MP', 'MH', 'DL'

    class Meta:
        verbose_name = 'State'
        verbose_name_plural = 'States'
        ordering = ['name']
        unique_together = [('country', 'name')]

    def __str__(self):
        return self.name


class District(models.Model):
    """Districts within a state."""
    state = models.ForeignKey(
        State, on_delete=models.CASCADE, related_name='districts'
    )
    name = models.CharField(max_length=100, db_index=True)

    class Meta:
        verbose_name = 'District'
        verbose_name_plural = 'Districts'
        ordering = ['name']
        unique_together = [('state', 'name')]

    def __str__(self):
        return f"{self.name}, {self.state.name}"


class City(models.Model):
    """Cities / towns within a district."""
    district = models.ForeignKey(
        District, on_delete=models.CASCADE, related_name='cities'
    )
    name = models.CharField(max_length=100, db_index=True)

    class Meta:
        verbose_name = 'City'
        verbose_name_plural = 'Cities'
        ordering = ['name']
        unique_together = [('district', 'name')]

    def __str__(self):
        return f"{self.name}, {self.district.name}"


class Pincode(models.Model):
    """Indian postal pincodes, linked to a city."""
    city = models.ForeignKey(
        City, on_delete=models.CASCADE, related_name='pincodes'
    )
    code = models.CharField(max_length=10, db_index=True)

    class Meta:
        verbose_name = 'Pincode'
        verbose_name_plural = 'Pincodes'
        ordering = ['code']
        unique_together = [('city', 'code')]

    def __str__(self):
        return f"{self.code} ({self.city.name})"


class Area(models.Model):
    """Named localities / areas within a pincode."""
    pincode = models.ForeignKey(
        Pincode, on_delete=models.CASCADE, related_name='areas'
    )
    name = models.CharField(max_length=200, db_index=True)

    class Meta:
        verbose_name = 'Area / Zone'
        verbose_name_plural = 'Areas / Zones'
        ordering = ['name']
        unique_together = [('pincode', 'name')]

    def __str__(self):
        return f"{self.name} - {self.pincode.code}"
