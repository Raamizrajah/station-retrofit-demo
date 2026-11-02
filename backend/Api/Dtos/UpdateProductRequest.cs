using StationRetrofit.Api.Models;

namespace StationRetrofit.Api.Dtos;

public record UpdateProductRequest(string? Name, string? Sku, ProductStatus? Status);
