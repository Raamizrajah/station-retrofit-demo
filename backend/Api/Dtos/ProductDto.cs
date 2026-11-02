using StationRetrofit.Api.Models;

namespace StationRetrofit.Api.Dtos;

public record ProductDto(int Id, string Name, string Sku, ProductStatus Status, DateTime CreatedAt, int PriceCount);
