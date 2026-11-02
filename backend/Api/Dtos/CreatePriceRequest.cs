using StationRetrofit.Api.Models;

namespace StationRetrofit.Api.Dtos;

public record CreatePriceRequest(int ProductId, string Currency, decimal Amount, PriceType Type, DateTime ValidFrom, DateTime? ValidTo);
